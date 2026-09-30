# CLI demo: policy, gateway, tool, evidence

The smallest local walkthrough of the path CausalMesh exists to enforce:

```
Agent -> CausalMesh SDK -> Tool Gateway -> Policy / Contract Gate -> Tool Handler -> Evidence
```

It needs no API key, no hosted model, no paid service and no network beyond
`localhost`. Nothing is written to disk. It is a demonstration of a pre-alpha
SDK, not a deployment recipe.

## Set up

From the repository root, on Python 3.11 or newer:

```bash
pip install -e ".[server]"
cd examples/cli_demo
```

## The journey

**1. Initialize.** In any empty project directory, `causalmesh init` writes a
starter `causalmesh.yaml` with one empty role. This directory already holds the
finished contract: the same file with `owns` filled in for two agents.

```bash
causalmesh init            # in a new project: writes a starter contract
```

**2. Declare who may touch what.** Open `causalmesh.yaml`. `coding-agent` owns
`src/` and `tests/`; `dba-agent` owns `production/`. Only arm `C3` refuses.

```bash
causalmesh policy validate       # VALID ... arm: C3  roles: 2
causalmesh policy show           # the contract, as the gate reads it
```

**3. Ask the gate, before anything runs.** `policy check` answers whether an
action would be allowed. It records nothing and exits `0` for allowed, `1` for
refused.

```bash
causalmesh policy check --agent coding-agent --kind path --name src/app.py
# ALLOW  path:src/app.py

causalmesh policy check --agent coding-agent --kind path --name production/schema.sql
# REFUSE  path:production/schema.sql
#        ownership  'production/schema.sql' is owned by 'dba-agent', not 'coding-agent'
```

**4. Register a tool.** `gateway.py` holds the tool (`write_file`, a plain Python
function that prints when it runs) and registers it with the SDK:

```python
mesh = CausalMesh.from_config("causalmesh.yaml", seed=DEMO_SEED)
mesh.register_tool(Tool(name="write_file", handler=write_file, kind="filesystem",
                        mutating=True, resource_args=["path"]))
app = create_app(mesh=mesh, agent_tokens={"coding-agent": token})
```

`mutating=True` means the gate is consulted before the handler runs, and
`resource_args=["path"]` names the argument the gate checks against the
contract. The token is bound to `coding-agent`: the gateway takes the agent from
the token and refuses a request that names another.

**5. Start the gateway** (terminal 1):

```bash
export CODING_AGENT_TOKEN=cm-demo-token-0001-abcdef      # Windows PowerShell: $env:CODING_AGENT_TOKEN = "..."
python gateway.py
# INFO:     Uvicorn running on http://127.0.0.1:8420
```

**6. An authorized call** (terminal 2, same `CODING_AGENT_TOKEN`):

```bash
python client.py tools
python client.py write src/app.py "print(1)"
# HTTP 200  {"allowed": true, "executed": true, "recorded": true, "event_id": "sdk_coding-agent_000001", ...}
```

Terminal 1 prints `[handler] write_file src/app.py`: the handler ran.

**7. A denied call:**

```bash
python client.py write production/schema.sql "DROP TABLE users;"
# HTTP 403  {"detail": {"message": "'production/schema.sql' is owned by 'dba-agent', not 'coding-agent'",
#                       "rule": "ownership", "event_id": "sdk_coding-agent_000002", "recorded": true}}
```

Terminal 1 prints **nothing**: no `[handler]` line, because the handler never
ran. The refusal was recorded all the same.

**8. Read the evidence and verify it.**

```bash
python client.py evidence          # both calls, signed and chained
python verify_evidence.py --tamper
# recorded chain: valid=True events=2 failures=0
# forged copy: the denied call is rewritten as 'executed'
# forged chain  : valid=False events=2 failures=1
# tampering detected
```

`verify_evidence.py` builds the key ring from the operator's keys, not from the
evidence. A verifier that took public keys out of the records it was checking
could not tell a forged, re-signed log from a real one.

## Or run all of it unattended

```bash
python run_demo.py      # 23 checks: policy, ALLOW, DENY, handler not run, auth, bad input, evidence
```

It starts the gateway on a free port, drives it, verifies the evidence and stops
the gateway. It exits `0` only if every check held. `tests/integration/test_cli_demo.py`
runs it, so the demo cannot rot unnoticed.

## What is real, and what is only the demo

| Real, shipped | Only in this demo |
|---|---|
| `causalmesh init`, `policy validate`, `policy show`, `policy check` | `gateway.py`: a short script, because `causalmesh serve` cannot load tools yet |
| `CausalMesh`, `Tool`, `create_app(mesh=...)`, the gate, the ownership rule | the `/v1/evidence` route: CausalMesh ships no evidence endpoint |
| signed, hash-chained evidence; `verify_chain` and `PublicKeyRing` | `DEMO_SEED`: a public seed, so the keys and the key ring are reproducible |
| bearer-token auth with tokens bound to an agent | the in-memory `write_file` tool |

## Limits, stated plainly

- **Pre-alpha, not production-ready.** No TLS: run behind a TLS-terminating proxy.
  Identity is bound to a token, not cryptographically proven. Execution is serial.
- **Evidence lives in memory.** The SDK has no export and no persistence; the
  evidence is gone when the gateway stops. `causalmesh verify --run` reads
  experiment artifacts, not SDK sessions, and takes its keys from the records
  themselves, so it cannot check attribution the way `verify_evidence.py` does.
- **`causalmesh serve` registers no tools.** Its actual function today is gating
  `/v1/chat/completions`. See `docs/backlog.md`.
- **`policy show`, `policy check` and `serve` reject the SDK-only `agent:` and
  `tools:` sections** of `causalmesh.yaml` (exit 2). `policy validate` accepts them.
  This contract leaves them out for that reason.
- **Not built, and not part of this demo:** hosted-model runs, Anthropic, LangGraph
  and CrewAI adapters, human-in-the-loop approval, persistence, claims.
- **Timestamps are wall-clock,** so chain hashes differ from run to run. The
  behavior, the verdicts and the event ids do not.
