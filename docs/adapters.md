# Model adapters

Spec §8. Real language models driving the substrate, through the same
`CodingAgent` interface the scripted agent uses.

Status: describes Phase 1. All three adapters are built and tested against
a real HTTP endpoint. **No hosted model has been run** — see "What has not
been executed" below, which is the honest limit of what this page claims.

## The acceptance criterion

> Every existing coordination guarantee must hold identically with a real
> model driving. If a test only fails once the scripted agent is removed,
> that is signal the substrate was accidentally coupled to determinism.

That is the whole point of the phase. A guarantee that holds only for an
agent whose next action is known in advance was never a guarantee about
coordination — it was a guarantee about the script.

| Guarantee | Test |
|---|---|
| Chain verifies | `test_the_chain_verifies` |
| Attribution survives | `test_attribution_survives` |
| Containment holds | `test_containment_holds_against_a_hostile_model` |
| C0 isolation holds | `test_c0_isolation_holds` |
| Enforcement blocks | `test_enforcement_blocks_a_model_write` |
| Channel is the only route | `test_the_channel_is_the_only_route_information_takes` |

All hold. The last one did not exist until a mutation proved it was needed
— see below.

## Wire protocol, not vendor SDKs

`openai` 3.11 and `anthropic` 1.4 are both installed on this machine and
neither is used. Three reasons, in order of weight:

**Reproducibility (§84).** An SDK is a moving dependency whose retry
policy, default timeout and request shaping change between releases. A run
that cannot be re-executed in two years because a client library changed
its defaults is not reproducible. The bytes on the wire are the contract.

**Recorded confounds (§43).** Everything that could influence output —
endpoint, model, temperature, top_p, seed, max tokens — must be captured in
the run record. An SDK supplying its own defaults hides some of them.

**One code path.** Every provider and every local server speaks either the
OpenAI chat-completions shape or something one class away from it. Three
SDKs would be three failure modes to test.

`urllib` rather than `httpx`: standard library, so the runtime dependency
list stays as short as §7 asks and nothing can drift underneath a stored
run.

## What differs between providers

Not much, and it is all in `clients.py`:

| | request | system prompt | tokens |
|---|---|---|---|
| OpenAI | `messages` | a `role: system` message | `usage.prompt_tokens` |
| Anthropic | `messages` + `system` | a **top-level field** | `usage.input_tokens` |
| Local | OpenAI shape | as OpenAI | often absent |

**Anthropic is not "OpenAI with a different URL."** It rejects
`role: "system"` inside `messages`, so leaving the system prompt there
would fail the request — or worse, on a lenient proxy, silently drop the
agent's entire instruction set, which looks like a badly behaved model
rather than a broken adapter.

`LocalClient` is separate from `OpenAIClient` despite sharing a wire
format, because they differ in what they *require*: a local server needs no
key, and `OpenAIClient` deliberately refuses to run without one. Merging
them would mean weakening that check.

The Anthropic API version is pinned. A floating version means a stored run
cannot be replayed against the semantics it ran under.

## Tested against a real server, not a mock

`tests/support/fake_model_server.py` binds a socket, accepts connections,
parses JSON bodies and returns JSON responses. The adapters are exercised
over genuine network I/O.

The difference is not academic. A patched transport tests that the adapter
*calls a function*; this tests that it *speaks the protocol*. The
system-prompt hoisting is exactly the kind of thing a mock accepts happily
and a real endpoint rejects.

The server is scriptable — each agent gets a queue of replies — so tests
drive an exact sequence of tool calls deterministically. The
nondeterminism a live model adds is the thing under study elsewhere, not
something these tests should inherit.

Fault injection is real too: `fail_next(500)` returns an actual HTTP 500,
so the transport's error path runs rather than a raised exception standing
in for it.

## The action protocol

One JSON object per turn:

```json
{"tool": "write_file", "arguments": {"path": "...", "content": "..."},
 "reasoning": "why", "done": false}
```

**Strict by design.** A permissive parser that guessed what the model meant
would make behaviour depend on the parser's guesses rather than the model's
output, and two runs of the "same" model would differ because an ambiguity
resolved differently. Every rejection carries a classified `kind`
(`no_json`, `malformed_json`, `unknown_tool`, `bad_arguments`, …), so a
model that cannot follow the protocol shows up as **countable
non-compliance** rather than silently degraded behaviour.

Fenced and prose-wrapped JSON are handled, because models emit them no
matter how the prompt is worded. That is not guessing: the object itself is
still parsed strictly, with brace-balanced scanning so nested objects and
braces inside strings do not truncate the match.

A model naming a tool outside the controlled API is rejected at the parser
(`test_no_shell_tool_is_reachable`), before anything reaches the executor.

## Containment

`ModelAgent` never holds a `Toolbox`. It reaches tools only through
`ToolExecutor`, so there is no code path by which model output can touch
the filesystem without passing the gate and being recorded — not by
discipline, but because the object it would need is not reachable.

Two tests check this: one on a live agent's object graph, one asserting the
module imports no execution primitives (`subprocess`, `os`, `shutil`,
`pathlib`), so even an unused import would fail.

An earlier version grepped the module source for `"Toolbox"` and failed on
the docstring *explaining* the guarantee. It was testing the prose.

## The mutation that survived

Three guarantees were mutation-tested and caught their mutation:

| Mutation | Caught by |
|---|---|
| Stop hoisting Anthropic's system prompt | 2 tests |
| Accept unknown tool names | 2 tests |
| Refuse to record gate denials | (Phase 0) |

A fourth did **not**. Feeding delivered events straight into the model's
conversation — bypassing the channel entirely — passed all 21 tests.

That is the most serious defect available in this codebase. Peer
information would reach a model's context outside all accounting, and the
coordination-byte total would no longer be a complete account of what the
agent knew. C0 stayed safe only incidentally, because `NullChannel` raises
on non-empty input; under C2 the leak would have been silent.

`test_the_channel_is_the_only_route_information_takes` now closes it, and
fails against that mutation showing the raw leaked `Event` in the model's
context.

The general lesson, recorded because it will recur: the guarantees most
worth testing are the ones no test naturally covers, because they are
properties of what the code *does not* do.

## Determinism, precisely

`ModelSettings` defaults to `temperature=0.0`, `top_p=1.0`, and passes
`seed` where a provider accepts it.

**This does not make a model deterministic.** Temperature 0 is not a
reproducibility guarantee on any hosted provider: batching, model updates
behind an alias, and floating-point non-associativity on GPU all produce
variation. What the settings do is remove the randomness that *can* be
removed and record the rest.

The adapter records the model the provider says it used, which can differ
from the one requested when an alias resolves to a dated snapshot. The
actual one is the confound (§43).

Consequently, **a run with a hosted model is not bit-reproducible**, and no
part of this system claims otherwise. The chain is still verifiable — it
records what happened, which is a different property from being able to
make it happen again.

## What has not been executed

No hosted model has been run through this code. No OpenAI or Anthropic key
was available, and none was requested: spending money is a decision for the
operator, not something to do quietly during a build.

What that means precisely:

- **Tested:** the wire protocol both providers use, over real HTTP, with
  real error codes — request shape, header placement, response parsing,
  token extraction, failure classification.
- **Untested:** whether a real GPT or Claude model actually follows the
  action protocol reliably enough to complete a task, and what the
  protocol-failure rate is.

The second is a measurement this platform is built to make, not an
assumption it is entitled to. Running it needs a key and a budget.

`LocalClient` was likewise not exercised against a live local server —
Ollama, vLLM and LM Studio were all probed and none was running on this
machine. It speaks the same OpenAI shape the tests exercise, but "works
against Ollama specifically" is not established.

## Retry policy: there isn't one

The transport does not retry. A retry inside it would make the number of
model calls in a run depend on transient network conditions, and the token
accounting (§44) would silently include work the experiment did not intend.

`TransportError` marks 429 and 5xx as `retryable`, so a caller can decide —
and record the decision.
