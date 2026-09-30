"""The whole-run watchdog (`docs/backlog.md`, "Timeout as a distinct run state").

`ExperimentRunner` is sequential and runs agent code inside its own event
loop. A hung agent therefore hangs the scheduler, and a scheduler that is
hung cannot time anything out. Two layers get around that:

1. **A worker thread with its own event loop.** The run executes there. The
   scheduler's loop stays free to watch the clock, which is the property a
   timer inside the run could never have: an agent that blocks the thread it
   runs on (`time.sleep`, a busy loop, a native call) also blocks any
   watchdog scheduled on that thread.
2. **Escalation, in three steps.** At the limit the deadline is tripped, so a
   run that is merely slow notices at its next between-turns check and
   unwinds cleanly with its evidence (`tasks.deadline`). If it has not
   returned after `grace_s`, the awaiting task is cancelled, which frees an
   agent stuck in an `await`. If it still has not returned after another
   `grace_s`, the thread is abandoned.

**Why a thread and not a subprocess.** A subprocess is the only mechanism
that can end a run that never returns control, and it is the stronger one.
It is not what this is, for three reasons that are specific to this codebase
rather than to Windows: a run's inputs (`RunConfig.checkpoint_handler`, a
`TaskDefinition` whose scenario an operator or test built in memory) are not
all picklable; a `spawn` child pays the full import of `causalmesh` per run,
which lands inside the timing the coordination-cost measurement (§44) is
about; and the tests' hung agents are injected in-process. Threads are
portable across Windows, Linux and macOS with the same semantics.

**What the thread strategy cannot do.** Python cannot kill a thread. An
agent blocked in a call that never returns (`time.sleep(3600)` on the loop's
own thread, a native call) is *abandoned*, not stopped: the thread is a
daemon, so it cannot keep the interpreter alive, but it keeps running until
that call returns. Three things bound the damage and one is not bounded:

- the abandoned thread can only write into its own run's workspace and its
  own in-memory chain, none of which the recorded artifact reads;
- the run's evidence is taken from the relay by the scheduler, not handed
  over by the run, so an abandoned run still yields the chain it had written;
- `RunTimedOutError.thread_abandoned` and the artifact envelope record that
  it happened, so it is visible rather than silent;
- **not bounded:** the abandoned thread keeps consuming CPU or holds
  resources while later runs execute, which can perturb their timings. That
  is the sequential-execution guarantee (`loop.py`) weakened, and the
  envelope flag is how an analysis can exclude the runs it may have touched.
  Ending such a thread for real needs process isolation; it is a tracked
  backlog item, not something this module pretends to have solved.

Nothing timed here is ever signed. See `tasks.deadline`.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ..tasks.deadline import PartialRun, RunDeadline, RunTimedOutError

__all__ = ["run_with_deadline"]

T = TypeVar("T")

DEFAULT_GRACE_S = 1.0


async def run_with_deadline(
    work: Callable[[RunDeadline], Awaitable[T]],
    *,
    run_id: str,
    limit_s: float,
    grace_s: float = DEFAULT_GRACE_S,
) -> T:
    """Run `work` under a wall-clock limit, or raise `RunTimedOutError`.

    `work` receives the `RunDeadline` to hand to `execute_task`. Any
    exception `work` raises before the limit is re-raised unchanged, so a
    harness failure is still a failure and is recorded as one. A result
    returned before the limit is returned as is.

    Once the limit has passed the run is TIMED_OUT, whatever it then does:
    a run that limps to a normal finish during the grace period has still
    overrun, and its result is discarded (`late_result_discarded`) rather
    than counted, because a budget that a slow enough run can talk its way
    past is not a budget.
    """
    if grace_s < 0:
        raise ValueError(f"grace_s must not be negative, got {grace_s}")

    deadline = RunDeadline(limit_s)
    main_loop = asyncio.get_running_loop()
    finished = asyncio.Event()
    started = time.monotonic()

    box: dict[str, Any] = {}
    lock = threading.Lock()
    handle: dict[str, Any] = {}

    def notify() -> None:
        # The scheduler's loop may be gone by the time an abandoned thread
        # finally returns; that is expected, not an error.
        with contextlib.suppress(RuntimeError):
            main_loop.call_soon_threadsafe(finished.set)

    def worker() -> None:
        loop = asyncio.new_event_loop()
        handle["loop"] = loop

        async def main() -> T:
            handle["task"] = asyncio.current_task()
            return await work(deadline)

        try:
            try:
                value = loop.run_until_complete(main())
            except BaseException as exc:
                with lock:
                    box["error"] = exc
            else:
                with lock:
                    box["value"] = value
        finally:
            with contextlib.suppress(Exception):
                loop.close()
            notify()

    thread = threading.Thread(target=worker, name=f"run-{run_id}", daemon=True)

    async def wait(seconds: float) -> bool:
        try:
            await asyncio.wait_for(finished.wait(), timeout=seconds)
        except TimeoutError:
            return finished.is_set()
        return True

    def cancel_worker() -> None:
        loop, task = handle.get("loop"), handle.get("task")
        if loop is not None and task is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(task.cancel)

    thread.start()
    try:
        in_time = await wait(limit_s)
        if in_time:
            error = box.get("error")
            if not isinstance(error, RunTimedOutError):
                if error is not None:
                    raise error
                return box["value"]  # type: ignore[no-any-return]

        deadline.trip()
        settled = await wait(grace_s)
        if not settled:
            cancel_worker()
            settled = await wait(grace_s)
    except asyncio.CancelledError:
        # The scheduler itself is being torn down (Ctrl+C, a cancelled
        # collection): do not leave the run executing behind it.
        deadline.trip()
        cancel_worker()
        raise

    elapsed = time.monotonic() - started
    error = box.get("error")

    if isinstance(error, RunTimedOutError):
        error.limit_s = limit_s
        error.elapsed_s = elapsed
        raise error

    abandoned = not settled
    late = settled and error is None
    partial = _partial_from_outside(deadline, run_id, abandoned=abandoned, error=error)
    detail = (
        "the run never returned control and its thread was abandoned"
        if abandoned
        else "the run finished after its budget was already spent; its result is discarded"
        if late
        else f"the run was interrupted and raised {type(error).__name__}: {error}"
    )
    raise RunTimedOutError(
        f"run exceeded its {limit_s:g}s wall-clock limit ({detail})",
        detected_by="abandoned" if abandoned else "cancelled",
        partial=partial,
        limit_s=limit_s,
        elapsed_s=elapsed,
        thread_abandoned=abandoned,
        late_result_discarded=late,
    )


def _partial_from_outside(
    deadline: RunDeadline,
    run_id: str,
    *,
    abandoned: bool,
    error: BaseException | None,
) -> PartialRun | None:
    """The chain written so far, read by the scheduler rather than the run.

    None when the run never assembled a relay to read from. That is
    recorded as an unknown chain, not as an empty one.
    """
    snapshot = deadline.chain_snapshot()
    if snapshot is None:
        return None
    records, head = snapshot
    where = (
        "abandoned: the run never returned control"
        if abandoned
        else f"interrupted from outside: {type(error).__name__ if error else 'finished late'}"
    )
    return PartialRun(run_id=run_id, records=records, head_hash=head, where=where)
