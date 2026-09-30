"""Durable evidence for an SDK session: an append-only JSONL file.

``CausalMesh(evidence_path=...)`` writes every signed record to this file as
it is produced, so a session's evidence outlives the process.  What the file
promises, and what it does not:

- **Append-only, one record per line.**  A record is written, flushed and
  ``fsync``-ed before ``ingest`` returns.  Nothing is ever rewritten.
- **A torn write is detected, never absorbed.**  A crash in the middle of a
  write leaves a final line with no newline that is not a whole record.
  Opening the file refuses it (``EvidenceCorruptError``, ``torn=True``).
  ``recover_evidence=True`` is the explicit, reported repair: the fragment is
  moved to ``<file>.torn`` and the chain resumes from the last whole record.
  The tool call whose record was torn already ran; its evidence is the
  fragment, which is why it is kept rather than deleted.
- **Resumable.**  A restart re-verifies the whole file against the session's
  own keys, then continues the chain: the next record links to the last
  ``chain_hash`` and takes the next sequence.  Resuming therefore needs the
  same keys, meaning ``seed=`` or ``identity.keys``.  With random keys the
  old records do not verify and the session refuses to start.
- **One writer.**  An OS lock on ``<file>.lock`` stops a second live session
  appending to the same chain and forking it.
- **Fail closed.**  If a write fails, the session refuses every later call
  (``EvidenceUnavailableError``) instead of running tools with no record.

What it cannot do: dropping whole lines from the *end* of the file leaves a
shorter chain that still verifies.  Nothing inside the chain can show that
(``crypto/chain.py`` says so too); an external anchor of the head hash does.
``CausalMesh.evidence_head`` is the value to record elsewhere.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from causalmesh.crypto.chain import ChainedEvent
from causalmesh.crypto.keys import PublicKeyRing
from causalmesh.relay.core import Relay
from causalmesh.relay.store import ChainStore, StoreError
from causalmesh.verifier import verify_chain

from .errors import (
    EvidenceCorruptError,
    EvidenceError,
    EvidenceLockedError,
    EvidenceUnavailableError,
)

__all__ = [
    "EvidenceScan",
    "EvidenceStore",
    "last_event_counter",
    "load_evidence",
    "resume_chain",
    "scan_evidence",
    "write_evidence",
    "write_public_keys",
]

_SDK_EVENT_ID = re.compile(r"^sdk_.+_(\d+)$")


@dataclass(frozen=True, slots=True)
class EvidenceScan:
    """What is on disk in an evidence file, before anything is verified.

    ``records`` are the whole records, in order.  ``torn_tail`` is an
    incomplete final line (bytes) or ``None``.  ``valid_size`` is the byte
    length of the intact part: everything before the torn tail.
    ``unterminated`` is True when the last whole record lacks its newline (a
    crash between the record and the newline: nothing is lost, and the repair
    is one byte).
    """

    records: list[dict[str, Any]]
    torn_tail: bytes | None
    valid_size: int
    unterminated: bool


def scan_evidence(path: Path | str) -> EvidenceScan:
    """Read an evidence file and separate whole records from a torn tail.

    Raises ``EvidenceCorruptError`` for damage that is not a torn tail: a
    complete line in the middle of the file that is not a JSON object.  That
    is corruption or tampering, not an interrupted write, and no option
    repairs it.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise EvidenceError(f"no evidence file at {path}") from exc
    except OSError as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc

    records: list[dict[str, Any]] = []
    offset = 0
    line_number = 0
    torn_tail: bytes | None = None
    unterminated = False
    valid_size = 0

    while offset < len(data):
        newline = data.find(b"\n", offset)
        line_number += 1
        if newline == -1:
            segment = data[offset:]
            if segment.strip():
                parsed = _parse_line(segment)
                if isinstance(parsed, dict):
                    records.append(parsed)
                    unterminated = True
                    valid_size = len(data)
                else:
                    torn_tail = segment
                    valid_size = offset
            else:
                valid_size = offset
            break
        segment = data[offset:newline]
        offset = newline + 1
        valid_size = offset
        if not segment.strip():
            continue
        parsed = _parse_line(segment)
        if not isinstance(parsed, dict):
            raise EvidenceCorruptError(
                f"{path}: line {line_number} is not a JSON record and is not the last line. "
                "This is damage in the middle of the file, not an interrupted write; "
                "it cannot be repaired automatically."
            )
        records.append(parsed)

    return EvidenceScan(
        records=records, torn_tail=torn_tail, valid_size=valid_size, unterminated=unterminated
    )


def _parse_line(segment: bytes) -> Any:
    try:
        return json.loads(segment.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _torn_message(path: Path, scan: EvidenceScan) -> str:
    assert scan.torn_tail is not None
    return (
        f"{path}: the last line is incomplete ({len(scan.torn_tail)} bytes after "
        f"{len(scan.records)} whole records). A write was interrupted. The call it "
        "recorded may already have run. Pass recover_evidence=True to move the fragment "
        f"to {path.name}.torn and continue from the last whole record."
    )


def load_evidence(path: Path | str, *, allow_torn_tail: bool = False) -> list[dict[str, Any]]:
    """Read an evidence file into records, refusing a torn tail.

    This reads; it does not verify.  Hand the records to
    ``causalmesh.verifier.verify_chain`` with a key ring the operator holds,
    or run ``causalmesh verify --evidence FILE --keys DIR``.

    A torn final line raises ``EvidenceCorruptError`` (``torn=True``) unless
    ``allow_torn_tail`` is set, in which case the whole records before it
    are returned and the fragment is ignored.  Ignoring it is a choice the
    caller makes explicitly; it is never the default.
    """
    scan = scan_evidence(path)
    if scan.torn_tail is not None and not allow_torn_tail:
        raise EvidenceCorruptError(_torn_message(Path(path), scan), torn=True)
    return scan.records


def last_event_counter(records: Iterable[dict[str, Any]]) -> int:
    """The highest ``sdk_<agent>_<n>`` counter used in these records, or 0."""
    highest = 0
    for record in records:
        event_id = ((record.get("event") or {}).get("event_id")) or ""
        match = _SDK_EVENT_ID.match(str(event_id))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


class _FileLock:
    """A non-blocking, process-wide exclusive lock on a side file.

    Held on ``<evidence>.lock`` rather than the evidence file itself, so
    readers (``causalmesh verify``) are never blocked.  The OS drops the
    lock when the process dies, so a crash never leaves a stale lock.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any = None

    def acquire(self) -> None:
        handle = self._path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise EvidenceLockedError(
                f"{self._path.with_suffix('')} is open in another session "
                f"(lock held on {self._path.name}). Close that session first: two writers "
                "would fork the chain."
            ) from exc
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            handle.close()


class EvidenceStore(ChainStore):
    """A ``ChainStore`` that is a durable, resumable, single-writer JSONL file.

    Unlike ``ChainStore(path)``, which refuses an existing file because a
    *run* must not be reopened, this store loads what is already there so a
    *session* can continue it.  The relay does the verifying (see
    ``resume_chain``); this class owns the bytes.
    """

    def __init__(self, path: Path | str, *, recover: bool = False, fsync: bool = True) -> None:
        super().__init__(None, fsync=fsync)
        self._path = Path(path)
        self._poisoned: str | None = None
        self._fh: Any = None
        self.recovery: dict[str, Any] | None = None

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = _FileLock(self._path.with_name(self._path.name + ".lock"))
        self._lock_file.acquire()
        try:
            self._load(recover=recover)
            self._fh = self._path.open("ab", buffering=0)
        except BaseException:
            self._lock_file.release()
            raise

    def _load(self, *, recover: bool) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        scan = scan_evidence(self._path)
        if scan.torn_tail is not None:
            if not recover:
                raise EvidenceCorruptError(_torn_message(self._path, scan), torn=True)
            sidecar = self._path.with_name(self._path.name + ".torn")
            with sidecar.open("ab") as out:
                out.write(scan.torn_tail + b"\n")
                out.flush()
                os.fsync(out.fileno())
            os.truncate(self._path, scan.valid_size)
            self.recovery = {
                "torn_bytes": len(scan.torn_tail),
                "preserved_in": str(sidecar),
                "records_kept": len(scan.records),
            }
        elif scan.unterminated:
            with self._path.open("ab") as out:
                out.write(b"\n")
                out.flush()
                os.fsync(out.fileno())
        self._records = list(scan.records)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def failure(self) -> str | None:
        """Why the store stopped accepting writes, or ``None`` while healthy."""
        return self._poisoned

    def append(self, chained: ChainedEvent) -> None:
        """Write one record durably, then remember it.

        The file is written before memory is touched, so a failed write leaves
        the two agreeing.  A failed write also closes the store: the file's
        tail is in an unknown state and appending after it could join two
        records onto one line.  An attempt is made to cut the file back to
        its size before the write; either way the session stops.
        """
        record = chained.to_dict()
        line = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            if self._poisoned is not None:
                raise EvidenceUnavailableError(self._poisoned)
            if self._fh is None:
                raise StoreError(f"{self._path} is closed")
            good_size = os.fstat(self._fh.fileno()).st_size
            try:
                view = memoryview(line)
                while view:
                    written = self._fh.write(view)
                    view = view[written:]
                self._fh.flush()
                if self._fsync:
                    os.fsync(self._fh.fileno())
            except BaseException as exc:
                with contextlib.suppress(OSError):
                    self._fh.truncate(good_size)
                self._poisoned = (
                    f"writing to {self._path} failed ({type(exc).__name__}: {exc}); "
                    "no further calls will run in this session. Restart it to resume "
                    "from the last record that reached the disk."
                )
                raise EvidenceUnavailableError(self._poisoned) from exc
            self._records.append(record)

    def close(self) -> None:
        with self._lock:
            fh, self._fh = self._fh, None
            if fh is not None:
                try:
                    fh.flush()
                    if self._fsync:
                        os.fsync(fh.fileno())
                except OSError:
                    pass
                finally:
                    fh.close()
        self._lock_file.release()


def resume_chain(relay: Relay, store: EvidenceStore, *, run_id: str) -> int:
    """Verify what the store loaded and continue the relay's chain from it.

    Returns the number of records resumed (0 for a new or empty file).

    The check is against ``relay.key_ring()``, this session's own keys, and
    not the keys embedded in the records: a file signed by other keys is not
    this session's chain to extend, and extending it would attribute the old
    records to whoever holds today's keys.  Any failure refuses the resume
    and leaves the file untouched.
    """
    records = store.records()
    if not records:
        return 0

    result = verify_chain(records, relay.key_ring())
    if not result.valid:
        shown = "; ".join(f"{f.kind.value}: {f.detail}" for f in result.failures[:3])
        raise EvidenceCorruptError(
            f"{store.path} does not verify against this session's keys "
            f"({len(result.failures)} failure(s): {shown}). To resume, use the same seed= "
            "or identity.keys that signed it, and declare every agent it names. "
            "The file has not been modified."
        )

    foreign = sorted(
        {
            str(record["event"]["identity"]["run_id"])
            for record in records
            if record["event"]["identity"]["run_id"] != run_id
        }
    )
    if foreign:
        raise EvidenceCorruptError(
            f"{store.path} belongs to run {foreign[0]!r}, not {run_id!r}. "
            "Pass the run_id that wrote it, or a new evidence_path."
        )

    last = records[-1]
    relay.resume(
        head_hash=last["chain_hash"],
        next_sequence=int(last["event"]["sequence"]) + 1,
        event_ids=(record["event"]["event_id"] for record in records),
    )
    return len(records)


def write_evidence(path: Path | str, records: Iterable[dict[str, Any]]) -> Path:
    """Write records to `path` as JSONL, atomically.

    Written to a temporary file in the same directory, ``fsync``-ed, then
    renamed over the destination, so a reader sees the old file or the whole
    new one, never half of it.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("wb") as handle:
        for record in records:
            handle.write(
                (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return destination


def write_public_keys(ring: PublicKeyRing, directory: Path | str) -> list[Path]:
    """Write one ``<agent_id>.pub`` per agent: the format ``verify --keys`` reads.

    Each file holds the agent's 64-character hex Ed25519 public key and a
    newline.  Public keys only; no private material is written.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for agent_id in sorted(ring.keys):
        if any(ch in agent_id for ch in ":/\\"):
            raise EvidenceError(f"agent id {agent_id!r} cannot be used as a file name")
        file = target / f"{agent_id}.pub"
        file.write_text(ring.keys[agent_id] + "\n", encoding="ascii")
        written.append(file)
    return written
