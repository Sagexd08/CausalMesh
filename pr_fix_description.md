The CLI `serve` command dynamically imports `uvicorn` and `fastapi`. In CI environments where the optional `[server]` dependency group is not installed, running these integration tests triggers a `ClickException` during CLI invocation, failing the test unexpectedly.

This PR adds `pytest.importorskip` to `tests/integration/test_serve.py` so the module gracefully skips if the underlying server dependencies are unavailable, exactly like how we skip the server unit tests.
