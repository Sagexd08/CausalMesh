# Transcripts

Every terminal output in the video is read from a file here. None of it is typed by hand, and the code
shown in the editors is read from `examples/cli_demo/` itself when the video is built.

They were captured by running a copy of `examples/cli_demo/` for real, on Windows 11 with Git Bash and
Python 3.12, in a fresh virtualenv with `pip install -e ".[server]"`, in one session, so the gateway log,
the evidence hashes and the verifier output all come from the same run. The commands are exactly the
commands shown on screen.

| File | Command |
|---|---|
| `init.txt`, `init_causalmesh.yaml` | `causalmesh init` in an empty directory, and the file it wrote |
| `validate.txt` | `causalmesh policy validate` (in `examples/cli_demo/`) |
| `show.txt` | `causalmesh policy show` (captured as a cp1252 console gets it, so an ASCII table) |
| `check_allow.txt` | `causalmesh policy check --agent coding-agent --kind path --name src/app.py` (exit 0) |
| `check_deny.txt` | `causalmesh policy check --agent coding-agent --kind path --name production/schema.sql` (exit 1) |
| `gateway.log` | the stdout of `python gateway.py` for the whole session |
| `exec_allow.txt` | `python client.py write src/app.py "print(1)"` (HTTP 200, exit 0) |
| `exec_deny.txt` | `python client.py write production/schema.sql "DROP TABLE users;"` (HTTP 403, exit 1) |
| `evidence.txt` | `python client.py evidence` (used for the hashes on the evidence cards) |
| `verify.txt` | `python verify_evidence.py --tamper` (exit 0) |

`python build_index.py` refuses to build unless these agree with each other: the gateway log holds exactly
one `[handler]` line and it is for `src/app.py`; the denied call's HTTP 403 names the `ownership` rule; the
two evidence records link (`previous_hash` of event 2 is `chain_hash` of event 1); and the digest the
verifier printed for the forged record is the real `chain_hash` of event 2.

## What the video adds, and what it leaves out

- The badges, the `200 ALLOWED` / `403 DENIED` chips, the "no [handler] line" marker and the evidence cards
  are drawn from the values in these files. They are annotation, not extra output.
- The video shows `gateway.log` up to the `403 Forbidden` line. The log continues with two
  `GET /v1/evidence` lines, from `client.py evidence` and `verify_evidence.py`, which the video does not show.
- The `examples/cli_demo/causalmesh.yaml` shown in scene 2 is the demo's contract: the starter that
  `causalmesh init` writes (scene 1, an `agent_a` with `owns: []`) with the owners filled in. The video
  labels the file by its path so the two are not mistaken for one another.
- `causalmesh init` prints the absolute path it wrote. It is a neutral scratch path here.
- Each pane in the split screen is a separate terminal. The token in `export CODING_AGENT_TOKEN=...` is the
  throwaway value printed in `examples/cli_demo/README.md`.

## What the demo is, and is not

- `gateway.py` is a short script a developer writes: it loads `causalmesh.yaml`, registers one tool with the
  SDK, and builds the FastAPI app with `create_app(mesh=...)`. `causalmesh serve` cannot load tools yet, so a
  script like this is how a tool-serving gateway is built today.
- The `/v1/evidence` route is the demo's own code, behind the same bearer token. CausalMesh ships no
  evidence endpoint; the SDK's evidence lives in memory in the process that recorded it, and SDK persistence
  is not built (see `docs/backlog.md`).
- `verify_evidence.py` builds the verifier's key ring from the operator's own keys, not from the records.
- Not shown, not claimed: TLS (there is none), persisted evidence, a hosted model, real CooperBench runs, or
  human-rater results. The demo signs with a fixed public seed, so its evidence is reproducible and is not
  a secret.
