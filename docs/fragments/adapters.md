# Fragment: adapters track (for the integrator)

Not a permanent doc. Contents to merge into `CHANGELOG.md`, `docs/backlog.md`,
`pyproject.toml` and `README.md`, which this track did not edit.

## Summary

`causalmesh.integrations` gains three adapters (`AnthropicAdapter`,
`LangGraphAdapter`, `CrewAIAdapter`) beside the existing Generic, OpenAI and
LangChain ones, and the shared machinery is now in one place. Every adapter
runs a call through `BaseFrameworkAdapter.observe` / `aobserve`, which call
`CausalMesh.execute` / `execute_async`: one authorization path, no adapter
calls a handler or builds a gate. Model mistakes come back as `Action failed:`
answers; an unknown agent raises `UnknownAgentError` before the gate or the
handler, on both the sync and async paths, through every adapter.

Nothing here was run against a real hosted model or a real agent loop.
LangChain and LangGraph were tested against the real packages with scripted
fake chat models. CrewAI was tested only against a minimal fake of
`crewai.tools.BaseTool`: the package is not installed and its contract was
written from its public interface.

## CHANGELOG bullets

Added:

- `AnthropicAdapter`: Anthropic Messages `tool_use` blocks in, `tool_result`
  blocks out (with `is_error`), tool definitions with `input_schema`. No vendor
  SDK; accepts plain dicts or SDK block objects. Sync and async
  (`handle_tool_use(s)`, `handle_message`, and `a`-prefixed twins).
- `LangGraphAdapter`: the LangChain adapter's tools plus `tool_node()`, a real
  `langgraph.prebuilt.ToolNode`. Tested with a real `ToolNode` in a
  `StateGraph` and a prebuilt agent driven by a scripted fake model.
- `CrewAIAdapter`: `crewai.tools.BaseTool` subclasses that route through the
  gate, sync (`_run`) and async (`_arun`). Tested against a fake `BaseTool`
  only; the real package has not been run.
- `BaseFrameworkAdapter.observe` / `aobserve` and `Observation`: the single
  place a model-requested call becomes text, so every adapter classifies
  errors the same way. `bind_arguments` for adapters that receive positional or
  keyword arguments.
- `tests/integration/test_adapter_gate.py`: one set of safety properties (allowed
  call goes through the gate and is recorded, denied call never reaches the
  handler, model mistakes are answers, unknown agent raises before gate and
  handler, all on the async path too) run through every adapter, plus a check
  that no adapter module calls a handler.

Fixed:

- `LangChainAdapter` tools raised `MissingResourceError` / `ToolNotFoundError`
  out of the caller's loop on a model's bad call; they now return
  `Action failed: ...`, as the OpenAI adapter already did. This is what lets
  the tools survive inside a LangGraph `ToolNode`, which re-raises by default.
- `tool_to_json_schema` dropped every parameter when one annotation could not
  be resolved (`NameError`), described `Optional[int]` and `X | None` as
  `string`, listed `*args` / `**kwargs` as required-looking properties, and
  ignored `Literal` and list item types. It now unwraps `Optional`, emits
  `enum` for `Literal`, `items` for `list[int]`-style hints, skips var
  parameters, and falls back to a string per parameter instead of losing them.
- `LangChainAdapter` handlers with `**kwargs` nested the extras under the
  parameter name instead of passing them as keywords.

## Backlog entries

Replace the last sentence of the "Framework adapters" bullet under "Developer
SDK" ("Anthropic `tool_use`, LangGraph and CrewAI adapters are still not
implemented") with the entries below.

### Framework adapters: Anthropic, LangGraph, CrewAI (2026-09-30)

**Built.** `AnthropicAdapter`, `LangGraphAdapter` and `CrewAIAdapter`, each
with a sync and an async path, exported from `causalmesh.integrations`, with
the import guard pattern of `LangChainAdapter` (importing the package works
without any framework; constructing an adapter without its framework raises
`ImportError` naming it). All route through `BaseFrameworkAdapter.observe`.
Pinned by `tests/integration/test_adapter_gate.py` (116 parametrised cases across
seven drivers), `test_anthropic_adapter.py`, `test_langgraph_adapter.py`,
`test_crewai_adapter.py` and `tests/unit/test_adapter_helpers.py`. The gate
property was mutation-checked: making the Anthropic, CrewAI, LangChain (async)
and OpenAI (async) paths call the handler directly, and making the shared
helper swallow every exception, each fail tests.

**What remains.**

- **The CrewAI adapter has never run against real `crewai`.** The tests use a
  fake `BaseTool` (pydantic model, `name` / `description` / `args_schema`, abstract
  `_run`, optional `_arun`, `run` / `arun`). Two real-package tests exist and are
  skipped when `crewai` is missing. Expect to adjust on first run: newer crewai
  versions rewrite `description` and validate arguments in a wrapper the fake
  does not have. Reason: crewai is heavy; installing it was out of scope and the
  disk was nearly full.
- **No hosted model has driven any adapter.** The Anthropic block shapes come
  from the public documentation, not from a live response; LangChain and
  LangGraph were run with scripted fake chat models. Reason: no keys, no
  spending in tests. What a real model does with these tools, including how
  often it emits arguments the schema rejects, is unmeasured.
- **LangGraph and LangChain are verified at one version each** (`langgraph`
  1.1.6, `langgraph-prebuilt` 1.0.9, `langchain-core` 1.2.26, `langchain` 1.2.15).
  Nothing was run at the floors proposed below, or at the `langchain-core>=1.3.3`
  floor the existing `langchain` extra declares (the machine has 1.2.26).
- **Tools are not filtered per agent.** Every registered tool is offered to
  every agent; the gate refuses at call time. Reason: `Tool` carries no
  per-agent visibility, and inventing one is a policy change.
- **The JSON Schema is shallow.** Scalars, `Optional`, `Literal`, `dict` and
  `list`/`tuple`/`set` of a scalar. Pydantic models, several-type unions and
  nested structures are described as `string`, and the handler receives what
  the model sent. Reason: the schema is deliberately stdlib-only.
- **A catch-all `ToolNode(handle_tool_errors=True)` swallows `UnknownAgentError`**
  into a tool message. The adapter cannot prevent it, since the node is the
  caller's; documented in `docs/adapters.md`.
- **Arguments a handler cannot bind** are answered before the gate by the
  LangChain, LangGraph and CrewAI adapters, but the OpenAI and Anthropic adapters
  pass them on, so the gate allows the call and the handler's `TypeError` is
  recorded as a failure. Both are safe (the handler does not run); they differ in
  what is on the chain.
- **Anthropic streaming and `server_tool_use` results** are not handled: only
  complete `tool_use` blocks are answered, and server-side tool blocks are
  skipped.
- **Handlers with `*args`** cannot be called through any adapter (the gateway calls
  `handler(**arguments)`); extra positionals are refused with `Action failed:`.

## pyproject optional-dependency extras

Existing (unchanged, for reference):

```toml
langchain = ["langchain-core>=1.3.3"]
```

Proposed additions. Only the installed versions were verified, so the floors
below are those versions, not the lowest that would work:

```toml
# LangGraphAdapter. Adapter tests were run against langgraph 1.1.6 and
# langgraph-prebuilt 1.0.9 (with langchain-core 1.2.26, not the langchain
# extra's 1.3.3 floor). ToolNode needs a graph runtime, so the tests build
# a StateGraph; older langgraph releases were not tried.
langgraph = [
    "langgraph>=1.1.6",
    "langchain-core>=1.3.3",
]
# CrewAIAdapter. NO floor verified: crewai was not installed and the adapter has
# only been run against a fake BaseTool. Add a floor after the two skipped
# real-package tests in tests/integration/test_crewai_adapter.py have run.
crewai = [
    "crewai",
]
```

`dev` needs nothing new for the adapters: `pydantic` (used by the CrewAI fake
tests, skipped with a reason if absent) already arrives with `server`, and
`langgraph` / `crewai` tests skip with a reason when the package is missing. If
the integrator wants those tests to run in the gate, add `langgraph` to `dev`.
Anthropic and OpenAI need no dependency at all.

## README / docs snippets

README, under the SDK section:

```python
from causalmesh import CausalMesh, Tool
from causalmesh.integrations import AnthropicAdapter

mesh = CausalMesh.from_config("causalmesh.yaml")
mesh.register_tool(Tool(name="write_file", handler=write_file, resource_args=["path"]))

adapter = AnthropicAdapter(mesh, agent_id="my-agent")
# pass adapter.get_tools() as `tools=` to the Messages API, then answer the
# model's tool_use blocks:
reply = adapter.handle_message(assistant_message)   # a user message, or None
```

One line for the adapter list: "OpenAI function calling, Anthropic `tool_use`,
LangChain, LangGraph and CrewAI, all through the same gate. Tested with
scripted payloads and fakes; no hosted model has driven any of them, and CrewAI
has not run against the real package." Do not describe any of it as validated
against real agents.
