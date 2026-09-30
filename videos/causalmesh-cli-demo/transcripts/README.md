# Transcripts

Every terminal output in the video is read from a file here. None of it is typed by hand.

They were captured by running `../demo-project/` for real, on Windows 11 with Git Bash, Python 3.12, in a
fresh virtualenv with `pip install -e ".[server]"`. The commands that produced them are exactly the
commands shown on screen.

| File | Command |
|---|---|
| `pip_install.excerpt.txt` | `pip install -e ".[server]"` (elided with `...`; the local path is shortened) |
| `init.txt` | `causalmesh init` |
| `validate.txt` | `causalmesh policy validate` |
| `show.txt` | `causalmesh policy show` (captured as a cp1252 console gets it: ASCII table) |
| `tools.txt` | `GET /v1/tools` |
| `check_allow.txt` / `check_deny.txt` | `causalmesh policy check --agent coding-agent --kind path --name ...` |
| `exec_allow.txt` / `exec_deny.txt` | `POST /v1/tools/write_file/execute` (200 and 403) |
| `evidence.txt` | `GET /v1/evidence` |
| `evidence_noauth.txt` | the same route with no token (401) |
| `gateway.log` | the gateway's stdout for the whole session |

## What the demo project is, and is not

- `demo-project/gateway.py` is a short script a developer writes: it loads `causalmesh.yaml`, registers one
  tool with the SDK, and builds the FastAPI app with `create_app`. `causalmesh serve` cannot load tools yet,
  so a script like this is how a tool-serving gateway is built today.
- The `/v1/evidence` route is the demo's own code. It returns `mesh.audit_events()` behind the same bearer
  token. CausalMesh does not ship an evidence endpoint; the SDK's evidence lives in memory in the process
  that recorded it (SDK persistence is not built, see `docs/backlog.md`).
- The token in the transcripts (`cm-dev-...`) is a throwaway value for this demo.
- There is no `causalmesh execute` command. Tools are executed over HTTP; the video uses `curl`.

## Known issue found while capturing

`causalmesh policy validate` is documented to check the Phase 1 `agent:` and `tools:` fields, but it rejects
both ("unknown key(s) in top level: agent"), including in the repository's own `examples/causalmesh.yaml`,
which the SDK loads fine. The demo contract omits `agent:` so the CLI and the SDK agree. This is not fixed
here.
