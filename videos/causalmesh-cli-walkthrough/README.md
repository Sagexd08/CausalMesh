# causalmesh-cli-walkthrough

An 87-second walkthrough of `examples/cli_demo/`: a developer's contract, a tool behind the SDK, an
allowed call, a denied call whose handler never runs, and evidence that verifies (and fails when one
record is rewritten). Pre-alpha, local SDK and gateway only.

Every terminal output comes from `transcripts/` (a real run of the fixture, see
`transcripts/README.md`) and the code in the editors is read from `examples/cli_demo/`.

| Time | Scene | Caption |
|---|---|---|
| 0:00 | `causalmesh init`, and the starter `causalmesh.yaml` it writes | Start with a policy. |
| 0:07 | the demo's contract; `policy validate`; `policy show` | Declare who may touch what. |
| 0:16 | `gateway.py`: `from_config`, `register_tool`, `mutating=True`, `resource_args=["path"]` | Put your tool behind the SDK. |
| 0:26 | `policy check`: `ALLOW`, then `REFUSE` with `ownership` | The gate decides before execution. |
| 0:36 | gateway and client side by side: 200, `recorded: true`, one `[handler]` line | Authorized: the tool runs. |
| 0:49 | the same call for `production/schema.sql`: 403, `ownership`, no `[handler]` line | Denied: the handler never runs. |
| 1:00 | `verify_evidence.py --tamper`: valid, then a rewritten record rejected | Every call leaves evidence. |
| 1:14 | the whole path, then the end card | Policy before execution. Evidence after execution. |

The end card says pre-alpha and lists three limits (in-memory evidence, no TLS, not production-ready).

## Rebuild

```bash
python build_index.py                 # writes index.html; stops if the transcripts disagree
npx hyperframes@0.8.81 check          # lint
npx hyperframes@0.8.81 snapshot --at 21,45.8,53.9   # stills, to look at
npx hyperframes@0.8.81 render         # writes renders/
```

Needs Chrome and ffmpeg. Where the bundled headless browser is blocked, set `HYPERFRAMES_BROWSER_PATH` to
an installed Chrome. To re-capture the transcripts, run the fixture again (`examples/cli_demo/README.md`)
and copy the outputs into `transcripts/` under the names listed there.

The music bed and sound effects in `assets/` are the ones `../causalmesh-cli-demo/` uses.
