# Model adapters

Spec §8. Real language models driving the substrate, through the same
`CodingAgent` interface the scripted agent uses.

Status: describes Phase 1. All three adapters are built and tested against
a real HTTP endpoint. **No hosted model has been run** — see "What has not
been executed" below, which is the honest limit of what this page claims.

## Framework adapters (the SDK side)

The rest of this page is about the harness's model adapters. This section is
about the other direction: `causalmesh.integrations`, which puts the SDK's
gate in front of the tools of an agent built with someone else's framework.
Agent -> CausalMesh SDK -> Tool Gateway -> Policy/Contract Gate -> Tool
Handler -> Evidence.

There is one authorization path. Every adapter hands a call to
`BaseFrameworkAdapter.observe` / `aobserve`, which call
`CausalMesh.execute` / `execute_async`. No adapter calls a handler, and none
builds a gate. `tests/integration/test_adapter_gate.py` checks that two ways:
behaviourally (a counter on the boundary and one on the handler, through every
adapter) and structurally (no adapter module contains a call to `.handler(...)`).

| Adapter | Speaks | Needs | Async |
|---|---|---|---|
| `GenericAdapter` | `call_tool(name, args)` returning a `GatewayResult` | nothing | `acall_tool` |
| `OpenAIAdapter` | Chat Completions `tool_calls` -> `role: tool` messages | nothing | `ahandle_tool_call(s)` |
| `AnthropicAdapter` | Messages API `tool_use` blocks -> `tool_result` blocks, `is_error` | nothing | `ahandle_tool_use(s)`, `ahandle_message` |
| `LangChainAdapter` | `langchain_core` `StructuredTool` | `langchain-core` | `ainvoke` |
| `LangGraphAdapter` | the same tools, plus `tool_node()` for a `ToolNode` | `langgraph` | `ainvoke` |
| `CrewAIAdapter` | `crewai.tools.BaseTool` subclasses | `crewai` | `arun` |

Importing `causalmesh.integrations` needs none of the frameworks. Constructing
an adapter whose framework is missing raises `ImportError` naming the package.

**What the model gets to see.** A denial is `Action denied by policy: ...`, a
handler failure and a mistake by the model are `Action failed: ...`, and on an
arm that does not enforce, a call C3 would refuse runs and says so. The
Anthropic adapter marks the first two `is_error: true`. Mistakes by the
model that run nothing and record nothing: an unregistered tool name, a
missing or unusable resource argument, arguments that are not a JSON object.
Arguments the handler cannot bind (an unexpected keyword) are answered before
the gate by the LangChain, LangGraph and CrewAI adapters; the OpenAI and
Anthropic adapters pass them through, so the gate allows the call, the handler
raises `TypeError`, and it comes back as `Action failed:` with the failure
recorded.

**What raises.** An unknown `agent_id` raises `UnknownAgentError`, before the
gate or the handler, on the sync and async paths, through every adapter. The
agent id is configuration, not model output; folding it into a tool message
would leave every call failing with no error. In LangGraph this means leaving
`ToolNode(handle_tool_errors=...)` at its default: a catch-all handler would
swallow it. `GenericAdapter` is called by the developer's own code rather than
a model, so it raises for every error, including an unregistered tool.

**How each is tested, and what that does not show.**

| Adapter | Tested against | Not validated |
|---|---|---|
| Generic, OpenAI, Anthropic | hand-written payloads in the documented shapes | any real model producing them; the Anthropic block shapes come from the public documentation, not from a live API response |
| LangChain | real `langchain-core` (1.2.26 here) | a hosted model driving an agent |
| LangGraph | real `langgraph` 1.1.6 and `langgraph-prebuilt` 1.0.9: a real `ToolNode` inside a `StateGraph`, and a prebuilt agent driven by a scripted fake chat model | a hosted model; any other version |
| CrewAI | a minimal fake of `BaseTool` (a pydantic model with `name`, `description`, `args_schema`, `_run`, `_arun`) | **the real package.** `crewai` is not installed here. The `BaseTool` contract is written from its public interface and has never been run against it. Two real-package tests are skipped, with a reason, until it is installed, and may need adjusting on first run |

None of these has been run through a real agent loop with a hosted model.
The LangChain and LangGraph runs use scripted messages, so they show the tools
work inside those frameworks and nothing about how a model uses them.

**Known limits.** Tools are not filtered per agent: every registered tool is
offered. Handlers must accept keyword arguments (the gateway calls
`handler(**arguments)`), so extra positional arguments are refused. The JSON
Schema covers scalars, `Optional`, `Literal`, `dict`, and `list`/`tuple`/`set`
of a scalar; anything else (Pydantic models, unions of several types) is
described as a string, and the handler receives whatever the model sent. Tool
calls in one Anthropic message run sequentially, in order.

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
