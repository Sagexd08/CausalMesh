"""Token lifecycle: expiry, revocation and rotation without a restart, and the record.

A bearer token used to be valid forever and could change only by restarting
the process. These tests pin what replaced that, and pin the failure choices
the design makes:

- A credential is valid while `now < expires_at`; the clock is injected.
- The tokens file is re-read when it changes, so removing an entry revokes it
  on the next request, and adding one (or overlapping two per agent) rotates.
- A reload that cannot be used keeps the LAST GOOD set and logs a warning that
  carries no file content. It neither locks everyone out nor opens anything.
- No token reaches a log line, an error body or the evidence chain, and the
  chain names the credential by the operator's label, never by the secret or a
  hash of it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from causalmesh import CausalMesh, Tool
from causalmesh.crypto.keys import PublicKeyRing
from causalmesh.policy.contract import Contract
from causalmesh.server import create_app, credentials as credentials_module
from causalmesh.server.credentials import (
    Credential,
    CredentialStore,
    parse_expiry,
    split_token_expiry,
)
from causalmesh.server.observability import RedactingFormatter, configure_logging
from causalmesh.verifier import verify_chain

CONTRACT = """
version: 1
roles:
  - agent_id: alice
    archetype: writer
    owns: [alice/]
  - agent_id: bob
    archetype: writer
    owns: [bob/]
policy:
  arm: C3
evidence:
  sign: true
"""

ALICE_OLD = "alice-old-token-000000000000"
ALICE_NEW = "alice-new-token-000000000000"
BOB = "bob-token-00000000000000000000"
OPERATOR = "operator-token-0000000000000"

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")


class Clock:
    """A settable wall clock, in seconds since the epoch."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def mesh(tmp_path: Path) -> CausalMesh:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    m = CausalMesh(
        agent_id="alice", contract=Contract.find(tmp_path), seed=b"lifecycle-00000000000000000000"
    )
    m.register_tool(Tool(name="echo", handler=lambda path: f"echo:{path}", resource_args=["path"]))
    return m


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _status(client: TestClient, token: str) -> int:
    return client.get("/v1/tools", headers=_auth(token)).status_code


def _write(path: Path, entries: list[dict[str, Any]], *, mode: int = 0o600) -> None:
    """Write a tokens file the way an operator would, atomically enough for a test."""
    path.write_text(json.dumps({"version": 1, "tokens": entries}), encoding="utf-8")
    os.chmod(path, mode)


def _entry(label: str, token: str, agent: str | None = None, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": label, "token": token, **extra}
    if agent is not None:
        entry["agent"] = agent
    return entry


def _bump(path: Path, seconds: float = 10.0) -> None:
    """Move the file's mtime forward, as a later edit would, however coarse the clock."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


@pytest.fixture
def tokens_path(tmp_path: Path) -> Path:
    return tmp_path / "tokens.json"


def _file_app(mesh: CausalMesh, path: Path, clock: Clock | None = None) -> TestClient:
    app = create_app(mesh=mesh, tokens_file=path, clock=clock or Clock())
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExpiry:
    def _client(self, mesh: CausalMesh, clock: Clock) -> TestClient:
        cred = Credential("alice-1", ALICE_OLD, "alice", expires_at=2_000.0)
        return TestClient(
            create_app(mesh=mesh, credentials=[cred], clock=clock), raise_server_exceptions=False
        )

    def test_a_token_works_until_its_expiry_and_not_at_it(self, mesh: CausalMesh) -> None:
        clock = Clock(1_999.999)
        client = self._client(mesh, clock)
        assert _status(client, ALICE_OLD) == 200
        clock.now = 2_000.0
        assert _status(client, ALICE_OLD) == 401, "valid while now < expires_at, so not at it"
        clock.now = 2_000.001
        assert _status(client, ALICE_OLD) == 401

    def test_an_expired_token_says_so_and_names_no_secret(
        self, mesh: CausalMesh, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = self._client(mesh, Clock(5_000.0))
        with caplog.at_level(logging.WARNING):
            response = client.get("/v1/tools", headers=_auth(ALICE_OLD))
        assert response.status_code == 401
        assert response.json() == {"detail": "Token expired"}
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert ALICE_OLD not in response.text + caplog.text
        assert "alice-1" in caplog.text, "the operator needs to know which credential it was"

    def test_a_wrong_token_is_not_told_it_expired(self, mesh: CausalMesh) -> None:
        client = self._client(mesh, Clock(5_000.0))
        assert client.get("/v1/tools", headers=_auth("guess")).json() == {"detail": "Invalid token"}

    def test_a_token_without_an_expiry_never_expires(self, mesh: CausalMesh) -> None:
        clock = Clock(10.0**10)
        client = TestClient(
            create_app(mesh=mesh, api_tokens={OPERATOR}, clock=clock), raise_server_exceptions=False
        )
        assert _status(client, OPERATOR) == 200

    def test_an_expired_token_does_not_disturb_another_credential(self, mesh: CausalMesh) -> None:
        creds = [
            Credential("alice-1", ALICE_OLD, "alice", expires_at=2_000.0),
            Credential("bob-1", BOB, "bob"),
        ]
        clock = Clock(3_000.0)
        client = TestClient(
            create_app(mesh=mesh, credentials=creds, clock=clock), raise_server_exceptions=False
        )
        assert _status(client, ALICE_OLD) == 401
        assert _status(client, BOB) == 200

    def test_the_expiry_of_a_file_credential_is_enforced_without_a_reload(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("op", OPERATOR, expires=3_000)])
        clock = Clock(2_999.0)
        client = _file_app(mesh, tokens_path, clock)
        assert _status(client, OPERATOR) == 200
        clock.now = 3_000.0
        assert _status(client, OPERATOR) == 401, "no file edit needed: expiry is judged per request"


@pytest.mark.unit
class TestExpiryParsing:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [
            ("1700000000", 1_700_000_000.0),
            ("2026-12-31T00:00:00Z", 1_798_675_200.0),
            ("2026-12-31T00:00:00+00:00", 1_798_675_200.0),
            ("2026-12-31T02:00:00+02:00", 1_798_675_200.0),
            ("2026-12-31T00:00:00", 1_798_675_200.0),  # no zone: UTC
            ("2026-12-31", 1_798_675_200.0),
        ],
    )
    def test_accepted_spellings(self, text: str, seconds: float) -> None:
        assert parse_expiry(text) == seconds

    @pytest.mark.parametrize("bad", ["", "soon", "2026-13-45", "-5", "0", True, None, [1]])
    def test_refused_spellings_never_echo_the_value(self, bad: object) -> None:
        with pytest.raises(ValueError) as caught:
            parse_expiry(bad)
        assert "soon" not in str(caught.value)

    @pytest.mark.parametrize(
        ("text", "token", "has_expiry"),
        [
            ("plain-token", "plain-token", False),
            ("abc@1700000000", "abc", True),
            ("abc@2026-12-31T00:00:00Z", "abc", True),
            ("a@b@2026-12-31", "a@b", True),
            ("user@example.com", "user@example.com", False),
            ("abc@12345", "abc@12345", False),  # too short to be unix time: part of the token
            ("abc@", "abc@", False),
            ("@1700000000", "@1700000000", False),  # nothing before it: all token
        ],
    )
    def test_token_expiry_suffix(self, text: str, token: str, has_expiry: bool) -> None:
        got_token, expiry = split_token_expiry(text)
        assert got_token == token
        assert (expiry is not None) is has_expiry

    def test_a_suffix_shaped_like_a_date_that_is_not_one_is_refused_not_guessed(self) -> None:
        with pytest.raises(ValueError, match="looks like an expiry"):
            split_token_expiry("abc@2026-13-45")


# ---------------------------------------------------------------------------
# Revocation and rotation without a restart
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTheTokensFile:
    def test_credentials_come_from_the_file(self, mesh: CausalMesh, tokens_path: Path) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice"), _entry("op", OPERATOR)])
        client = _file_app(mesh, tokens_path)
        assert _status(client, ALICE_OLD) == 200
        assert _status(client, OPERATOR) == 200
        assert _status(client, "guess") == 401

    def test_a_file_token_bound_to_an_agent_cannot_act_as_another(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice")])
        client = _file_app(mesh, tokens_path)
        response = client.post(
            "/v1/tools/echo/execute",
            json={"agent_id": "bob", "arguments": {"path": "bob/x"}},
            headers=_auth(ALICE_OLD),
        )
        assert response.status_code == 403

    def test_removing_a_token_revokes_it_on_the_next_request(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice"), _entry("bob-1", BOB, "bob")])
        client = _file_app(mesh, tokens_path)
        assert _status(client, ALICE_OLD) == 200
        _write(tokens_path, [_entry("bob-1", BOB, "bob")])
        _bump(tokens_path)
        assert _status(client, ALICE_OLD) == 401
        assert _status(client, BOB) == 200, "the others are untouched"

    def test_adding_a_token_takes_effect_without_a_restart(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice")])
        client = _file_app(mesh, tokens_path)
        assert _status(client, BOB) == 401
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice"), _entry("bob-1", BOB, "bob")])
        _bump(tokens_path)
        assert _status(client, BOB) == 200

    def test_rotation_has_an_overlap_window_then_the_old_token_goes(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("alice-2026-09", ALICE_OLD, "alice")])
        client = _file_app(mesh, tokens_path)

        # 1. Add the new token beside the old one: both are valid for alice.
        _write(
            tokens_path,
            [
                _entry("alice-2026-09", ALICE_OLD, "alice"),
                _entry("alice-2026-10", ALICE_NEW, "alice"),
            ],
        )
        _bump(tokens_path)
        assert _status(client, ALICE_OLD) == 200
        assert _status(client, ALICE_NEW) == 200

        # 2. Clients have moved: drop the old one.
        _write(tokens_path, [_entry("alice-2026-10", ALICE_NEW, "alice")])
        _bump(tokens_path, 20)
        assert _status(client, ALICE_OLD) == 401
        assert _status(client, ALICE_NEW) == 200

    def test_an_empty_list_revokes_everything_on_purpose(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("op", OPERATOR)])
        client = _file_app(mesh, tokens_path)
        assert _status(client, OPERATOR) == 200
        _write(tokens_path, [])
        _bump(tokens_path)
        assert _status(client, OPERATOR) == 401

    def test_flag_tokens_stay_valid_beside_the_file(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice")])
        app = create_app(mesh=mesh, api_tokens={OPERATOR}, tokens_file=tokens_path)
        client = TestClient(app, raise_server_exceptions=False)
        _write(tokens_path, [])
        _bump(tokens_path)
        assert _status(client, ALICE_OLD) == 401
        assert _status(client, OPERATOR) == 200

    def test_an_edit_inside_the_timestamp_granularity_is_still_seen(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        """Same size, same mtime, moments after the last read: the bytes decide."""
        first = "a" * 28
        second = "b" * 28
        _write(tokens_path, [_entry("op", first)])
        client = _file_app(mesh, tokens_path)
        assert _status(client, first) == 200
        before = tokens_path.stat().st_mtime_ns
        _write(tokens_path, [_entry("op", second)])
        os.utime(tokens_path, ns=(before, before))
        assert _status(client, second) == 200
        assert _status(client, first) == 401

    def test_a_reload_request_forces_a_re_read(self, mesh: CausalMesh, tokens_path: Path) -> None:
        """What SIGHUP does: the file looks unchanged (old, same size and mtime) but is not."""
        first, second = "c" * 28, "d" * 28
        _write(tokens_path, [_entry("op", first)])
        old = 1_000_000_000 * 10**9
        os.utime(tokens_path, ns=(old, old))
        app = create_app(mesh=mesh, tokens_file=tokens_path)
        client = TestClient(app, raise_server_exceptions=False)
        _write(tokens_path, [_entry("op", second)])
        os.utime(tokens_path, ns=(old, old))
        assert _status(client, second) == 401, "an unchanged signature is not re-read"
        app.state.credentials.request_reload()
        assert _status(client, second) == 200
        assert _status(client, first) == 401


# ---------------------------------------------------------------------------
# A reload that cannot be used keeps the last good set
# ---------------------------------------------------------------------------

LEAKY = "zzLEAKYzz-secret-that-must-never-be-logged"


@pytest.mark.integration
@pytest.mark.adversarial
class TestABadReloadKeepsTheLastGoodSet:
    @pytest.fixture
    def client(self, mesh: CausalMesh, tokens_path: Path) -> TestClient:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice"), _entry("op", OPERATOR)])
        return _file_app(mesh, tokens_path)

    def _break(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        _bump(path)

    @pytest.mark.parametrize(
        "broken",
        [
            f"tokens: [ {{id: a, token: {LEAKY}",  # unterminated flow mapping
            f"{{: {LEAKY}",
            f"- {LEAKY}\n",  # a list, not a mapping
            f"tokens: {LEAKY}\n",  # not a list
            f"tokens:\n  - id: x\n    token: {LEAKY}\n    surprise: 1\n",
            f"tokens:\n  - id: x\n    token: [{LEAKY}]\n",
            f"tokens:\n  - id: 'has space {LEAKY}'\n    token: {LEAKY}-2\n",
            f"tokens:\n  - id: dup\n    token: {LEAKY}-a\n  - id: dup\n    token: {LEAKY}-b\n",
            f"tokens:\n  - id: a\n    token: {LEAKY}\n  - id: b\n    token: {LEAKY}\n",
            f"tokens:\n  - id: a\n    token: {LEAKY}\n    agent: mallory\n",  # no key for it
            f"tokens:\n  - id: a\n    token: {LEAKY}\n    expires: 'never {LEAKY}'\n",
            f"version: 2\ntokens: []  # {LEAKY}\n",
            f"tokens: []\nextra: {LEAKY}\n",
        ],
    )
    def test_nothing_changes_and_nothing_leaks(
        self,
        client: TestClient,
        tokens_path: Path,
        caplog: pytest.LogCaptureFixture,
        broken: str,
    ) -> None:
        self._break(tokens_path, broken)
        with caplog.at_level(logging.DEBUG):
            assert _status(client, ALICE_OLD) == 200, "last good set must still authenticate"
            assert _status(client, OPERATOR) == 200
            assert _status(client, LEAKY) == 401, "a token that only a bad file named is not valid"
            assert _status(client, f"{LEAKY}-a") == 401
        assert "keeping the last good set" in caplog.text
        assert LEAKY not in caplog.text
        assert ALICE_OLD not in caplog.text and OPERATOR not in caplog.text

    def test_a_non_utf8_file_is_not_a_reason_to_lock_everyone_out(
        self, client: TestClient, tokens_path: Path
    ) -> None:
        tokens_path.write_bytes(b"\xff\xfe\x00tokens")
        os.chmod(tokens_path, 0o600)
        _bump(tokens_path)
        assert _status(client, OPERATOR) == 200

    def test_a_deleted_file_keeps_the_last_good_set(
        self, client: TestClient, tokens_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        tokens_path.unlink()
        with caplog.at_level(logging.WARNING):
            assert _status(client, OPERATOR) == 200
            assert _status(client, OPERATOR) == 200
        assert caplog.text.count("keeping the last good set") == 1, "one warning, not one a request"

    def test_fixing_the_file_recovers_and_applies_the_fix(
        self, client: TestClient, tokens_path: Path
    ) -> None:
        self._break(tokens_path, "tokens: [")
        assert _status(client, OPERATOR) == 200
        _write(tokens_path, [_entry("bob-1", BOB, "bob")])
        _bump(tokens_path, 30)
        assert _status(client, BOB) == 200
        assert _status(client, OPERATOR) == 401, "the fix revoked what it no longer lists"

    def test_the_last_good_set_still_honours_expiry(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        """Keeping the old set is not a way for a token to outlive its expiry."""
        _write(tokens_path, [_entry("op", OPERATOR, expires=5_000)])
        clock = Clock(1_000.0)
        client = _file_app(mesh, tokens_path, clock)
        assert _status(client, OPERATOR) == 200
        self._break(tokens_path, "tokens: [")
        assert _status(client, OPERATOR) == 200
        clock.now = 5_000.0
        assert _status(client, OPERATOR) == 401

    def test_a_bad_file_at_startup_is_refused_without_its_content(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        tokens_path.write_text(f"tokens: [ {LEAKY}", encoding="utf-8")
        os.chmod(tokens_path, 0o600)
        with pytest.raises(ValueError, match="tokens file") as caught:
            create_app(mesh=mesh, tokens_file=tokens_path)
        assert LEAKY not in str(caught.value)

    def test_a_missing_file_at_startup_is_refused(self, mesh: CausalMesh, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cannot be opened"):
            create_app(mesh=mesh, tokens_file=tmp_path / "absent.json")

    def test_a_file_naming_an_agent_without_a_key_is_refused_at_startup(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("m", OPERATOR, "mallory")])
        with pytest.raises(ValueError, match="no key for.*mallory"):
            create_app(mesh=mesh, tokens_file=tokens_path)

    def test_a_file_entry_that_repeats_a_flag_token_is_refused(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("dup", OPERATOR)])
        with pytest.raises(ValueError, match="same token"):
            create_app(mesh=mesh, api_tokens={OPERATOR}, tokens_file=tokens_path)


@pytest.mark.integration
@pytest.mark.adversarial
@posix_only
class TestFilePermissions:
    def test_a_group_or_world_readable_file_is_refused_at_startup(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("op", OPERATOR)], mode=0o644)
        with pytest.raises(ValueError, match=r"chmod 600") as caught:
            create_app(mesh=mesh, tokens_file=tokens_path)
        assert OPERATOR not in str(caught.value)

    @pytest.mark.parametrize("mode", [0o640, 0o604, 0o660, 0o666, 0o700 | 0o010])
    def test_any_group_or_other_bit_is_refused(
        self, mesh: CausalMesh, tokens_path: Path, mode: int
    ) -> None:
        _write(tokens_path, [_entry("op", OPERATOR)], mode=mode)
        with pytest.raises(ValueError, match="group or other"):
            create_app(mesh=mesh, tokens_file=tokens_path)

    def test_owner_only_modes_are_accepted(self, mesh: CausalMesh, tokens_path: Path) -> None:
        for mode in (0o600, 0o400):
            _write(tokens_path, [_entry("op", OPERATOR)], mode=mode)
            create_app(mesh=mesh, tokens_file=tokens_path)

    def test_a_file_that_becomes_permissive_is_not_reloaded(
        self, mesh: CausalMesh, tokens_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write(tokens_path, [_entry("op", OPERATOR)])
        client = _file_app(mesh, tokens_path)
        _write(tokens_path, [_entry("bob-1", BOB, "bob")], mode=0o644)
        _bump(tokens_path)
        with caplog.at_level(logging.WARNING):
            assert _status(client, OPERATOR) == 200
            assert _status(client, BOB) == 401
        assert "chmod 600" in caplog.text
        os.chmod(tokens_path, 0o600)
        _bump(tokens_path, 20)
        assert _status(client, BOB) == 200

    def test_a_directory_is_not_a_tokens_file(self, mesh: CausalMesh, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cannot be opened|not a regular file"):
            create_app(mesh=mesh, tokens_file=tmp_path)

    def test_the_mode_check_uses_the_opened_file(self, tokens_path: Path) -> None:
        _write(tokens_path, [_entry("op", OPERATOR)])
        assert stat.S_IMODE(tokens_path.stat().st_mode) == 0o600
        CredentialStore(tokens_file=tokens_path)


@pytest.mark.unit
class TestWindowsHasNoModeCheck:
    def test_mode_bits_are_not_consulted_where_they_mean_nothing(
        self, tokens_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tokens_path, [_entry("op", OPERATOR)], mode=0o666)
        monkeypatch.setattr(credentials_module, "_ENFORCE_FILE_MODE", False)
        assert CredentialStore(tokens_file=tokens_path).enabled


# ---------------------------------------------------------------------------
# Constant-time comparison is still the only comparison
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConstantTimeComparison:
    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, bytes]]:
        seen: list[tuple[bytes, bytes]] = []
        real = credentials_module.hmac.compare_digest

        def spy(a: Any, b: Any) -> bool:
            seen.append((a, b))
            return real(a, b)

        monkeypatch.setattr(credentials_module.hmac, "compare_digest", spy)
        return seen

    def _client(self, mesh: CausalMesh) -> TestClient:
        creds = [
            Credential("first", OPERATOR),
            Credential("second", ALICE_OLD, "alice", expires_at=2_000.0),
            Credential("third", BOB, "bob"),
        ]
        return TestClient(
            create_app(mesh=mesh, credentials=creds, clock=Clock(3_000.0)),
            raise_server_exceptions=False,
        )

    @pytest.mark.parametrize("presented", [OPERATOR, ALICE_OLD, BOB, "nope"])
    def test_every_credential_is_compared_whichever_one_matches(
        self, mesh: CausalMesh, calls: list[tuple[bytes, bytes]], presented: str
    ) -> None:
        """No early exit on a match, and expired credentials are compared too."""
        self._client(mesh).get("/v1/tools", headers=_auth(presented))
        assert len(calls) == 3
        assert {b for _, b in calls} == {t.encode() for t in (OPERATOR, ALICE_OLD, BOB)}
        assert all(a == presented.encode() for a, _ in calls)

    def test_the_comparison_stays_constant_time_after_a_reload(
        self, mesh: CausalMesh, tokens_path: Path, calls: list[tuple[bytes, bytes]]
    ) -> None:
        _write(tokens_path, [_entry("a", OPERATOR)])
        client = _file_app(mesh, tokens_path)
        _write(tokens_path, [_entry("a", OPERATOR), _entry("b", BOB, "bob")])
        _bump(tokens_path)
        client.get("/v1/tools", headers=_auth(OPERATOR))
        assert len(calls) == 2

    def test_no_credential_is_ever_compared_with_equality(self) -> None:
        source = Path(credentials_module.__file__).read_text(encoding="utf-8")
        assert "hmac.compare_digest(" in source
        assert "token ==" not in source and "== token" not in source
        assert "token in tokens" not in source.split("def lookup")[1].split("def credentials")[0]


# ---------------------------------------------------------------------------
# No secret in logs, errors or evidence
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNoSecretLeaks:
    def test_credential_objects_do_not_print_their_token(self) -> None:
        cred = Credential("c", OPERATOR)
        assert OPERATOR not in repr(cred) and OPERATOR not in str(cred)

    def test_a_label_that_is_a_pasted_secret_is_refused(self) -> None:
        secret = "pasted-by-mistake-0000000000"
        with pytest.raises(ValueError, match="must not be a secret"):
            Credential(secret, secret)
        with pytest.raises(ValueError):
            Credential("has space", OPERATOR)
        with pytest.raises(ValueError):
            Credential("x" * 65, OPERATOR)

    def test_reload_logs_name_labels_and_never_tokens(
        self, mesh: CausalMesh, tokens_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice")])
        client = _file_app(mesh, tokens_path)
        _write(tokens_path, [_entry("alice-2", ALICE_NEW, "alice")])
        _bump(tokens_path)
        with caplog.at_level(logging.DEBUG):
            _status(client, ALICE_NEW)
            _status(client, ALICE_OLD)
        assert "alice-2" in caplog.text and "alice-1" in caplog.text
        assert ALICE_NEW not in caplog.text and ALICE_OLD not in caplog.text

    def test_the_redacting_formatter_learns_a_token_added_by_a_reload(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(tokens_path, [_entry("alice-1", ALICE_OLD, "alice")])
        app = create_app(mesh=mesh, tokens_file=tokens_path)
        client = TestClient(app, raise_server_exceptions=False)
        store: CredentialStore = app.state.credentials
        formatter = RedactingFormatter("%(message)s", secrets=store.secrets)

        def render(text: str) -> str:
            record = logging.LogRecord("causalmesh.x", logging.INFO, "f", 1, text, None, None)
            return formatter.format(record)

        assert ALICE_NEW in render(f"oops {ALICE_NEW}"), "not a secret yet"
        _write(tokens_path, [_entry("alice-2", ALICE_NEW, "alice")])
        _bump(tokens_path)
        _status(client, ALICE_NEW)
        assert ALICE_NEW not in render(f"oops {ALICE_NEW}"), "a reloaded token is scrubbed"
        assert ALICE_OLD not in render(f"oops {ALICE_OLD}"), "a revoked token stays scrubbed"

    def test_configure_logging_accepts_a_live_secret_source(self) -> None:
        store = CredentialStore([Credential("c", OPERATOR)])
        undo = configure_logging(level="info", secrets=store.secrets)
        try:
            handler = logging.getLogger("causalmesh").handlers[-1]
            assert isinstance(handler.formatter, RedactingFormatter)
            record = logging.LogRecord("causalmesh.x", logging.INFO, "f", 1, OPERATOR, None, None)
            assert handler.filter(record)  # stamps request_id, as a real emit does
            assert OPERATOR not in handler.formatter.format(record)
        finally:
            undo()

    def test_a_401_body_never_contains_the_presented_token(self, mesh: CausalMesh) -> None:
        client = TestClient(
            create_app(mesh=mesh, api_tokens={OPERATOR}), raise_server_exceptions=False
        )
        response = client.get("/v1/tools", headers=_auth("presented-" + "p" * 30))
        assert "presented-" not in response.text


# ---------------------------------------------------------------------------
# The record: which credential acted
# ---------------------------------------------------------------------------


def _payloads(mesh: CausalMesh) -> list[dict[str, Any]]:
    return [e["event"]["payload"] for e in mesh.audit_events()]


@pytest.mark.integration
class TestTheChainNamesTheCredential:
    def _execute(self, client: TestClient, token: str, agent: str = "alice") -> Any:
        return client.post(
            "/v1/tools/echo/execute",
            json={"agent_id": agent, "arguments": {"path": f"{agent}/x"}},
            headers=_auth(token),
        )

    def test_a_tool_call_records_the_label_beside_identity_source(self, mesh: CausalMesh) -> None:
        creds = [Credential("alice-2026-09", ALICE_OLD, "alice")]
        client = TestClient(create_app(mesh=mesh, credentials=creds), raise_server_exceptions=False)
        assert self._execute(client, ALICE_OLD).status_code == 200
        payload = _payloads(mesh)[-1]
        assert payload["credential_id"] == "alice-2026-09"
        assert payload["identity_source"] == "token-bound"

    def test_a_chat_call_records_it_too(self, mesh: CausalMesh) -> None:
        creds = [Credential("gateway", OPERATOR)]
        client = TestClient(create_app(mesh=mesh, credentials=creds), raise_server_exceptions=False)
        client.post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "bob"},
            headers=_auth(OPERATOR),
        )
        payload = _payloads(mesh)[-1]
        assert payload["credential_id"] == "gateway"
        assert payload["identity_source"] == "asserted"

    def test_a_denied_call_carries_it(self, mesh: CausalMesh) -> None:
        creds = [Credential("alice-1", ALICE_OLD, "alice")]
        client = TestClient(create_app(mesh=mesh, credentials=creds), raise_server_exceptions=False)
        response = client.post(
            "/v1/tools/echo/execute",
            json={"agent_id": "alice", "arguments": {"path": "bob/x"}},
            headers=_auth(ALICE_OLD),
        )
        assert response.status_code == 403
        assert _payloads(mesh)[-1]["credential_id"] == "alice-1"

    def test_the_default_labels_come_from_configuration(self, mesh: CausalMesh) -> None:
        app = create_app(mesh=mesh, api_tokens={OPERATOR}, agent_tokens={"alice": ALICE_OLD})
        client = TestClient(app, raise_server_exceptions=False)
        self._execute(client, OPERATOR, "bob")
        self._execute(client, ALICE_OLD)
        assert [p["credential_id"] for p in _payloads(mesh)] == ["api-token", "agent-token:alice"]

    def test_with_auth_off_the_field_is_absent_not_a_made_up_value(self, mesh: CausalMesh) -> None:
        client = TestClient(create_app(mesh=mesh, auth_disabled=True))
        self._execute(client, "")
        assert "credential_id" not in _payloads(mesh)[-1]

    def test_the_label_is_the_operators_choice_and_not_the_token_or_a_digest_of_it(
        self, mesh: CausalMesh
    ) -> None:
        creds = [Credential("alice-1", ALICE_OLD, "alice")]
        client = TestClient(create_app(mesh=mesh, credentials=creds), raise_server_exceptions=False)
        self._execute(client, ALICE_OLD)
        blob = json.dumps(mesh.audit_events(), default=str)
        assert ALICE_OLD not in blob
        for digest in (hashlib.sha256, hashlib.sha1, hashlib.md5, hashlib.blake2b):
            assert digest(ALICE_OLD.encode()).hexdigest()[:16] not in blob

    def test_a_rotated_token_keeps_the_label_so_the_payload_is_reproducible(
        self, tmp_path: Path
    ) -> None:
        """Same operator config, different secrets: the same signed payload field."""

        def run(token: str, sub: str) -> dict[str, Any]:
            root = tmp_path / sub
            root.mkdir()
            (root / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
            m = CausalMesh(
                agent_id="alice",
                contract=Contract.find(root),
                seed=b"repro-000000000000000000000000",
            )
            m.register_tool(Tool(name="echo", handler=lambda path: path, resource_args=["path"]))
            client = TestClient(
                create_app(mesh=m, credentials=[Credential("alice-main", token, "alice")]),
                raise_server_exceptions=False,
            )
            assert self._execute(client, token).status_code == 200
            return _payloads(m)[-1]

        first = run(ALICE_OLD, "a")
        second = run(ALICE_NEW, "b")
        assert first["credential_id"] == second["credential_id"] == "alice-main"
        assert first["identity_source"] == second["identity_source"]

    def test_the_chain_verifies_with_the_label_in_it(self, mesh: CausalMesh) -> None:
        creds = [Credential("alice-1", ALICE_OLD, "alice")]
        client = TestClient(create_app(mesh=mesh, credentials=creds), raise_server_exceptions=False)
        for _ in range(3):
            self._execute(client, ALICE_OLD)
        client.post("/v1/chat/completions", json={"model": "m"}, headers=_auth(ALICE_OLD))
        events = mesh.audit_events()
        assert len(events) == 4
        assert verify_chain(events, PublicKeyRing.from_keypairs(mesh._relay._keypairs)).valid

    def test_evidence_says_which_of_two_overlapping_tokens_acted(
        self, mesh: CausalMesh, tokens_path: Path
    ) -> None:
        _write(
            tokens_path,
            [_entry("alice-old", ALICE_OLD, "alice"), _entry("alice-new", ALICE_NEW, "alice")],
        )
        client = _file_app(mesh, tokens_path)
        self._execute(client, ALICE_OLD)
        self._execute(client, ALICE_NEW)
        assert [p["credential_id"] for p in _payloads(mesh)] == ["alice-old", "alice-new"]


# ---------------------------------------------------------------------------
# Configuration that would mean less than it says is refused
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfigurationIsValidated:
    def test_two_credentials_with_one_label(self) -> None:
        with pytest.raises(ValueError, match="share the label"):
            CredentialStore([Credential("x", OPERATOR), Credential("x", BOB)])

    def test_two_credentials_with_one_token(self) -> None:
        with pytest.raises(ValueError, match="same token"):
            CredentialStore([Credential("x", OPERATOR), Credential("y", OPERATOR)])

    def test_a_blank_token_is_refused(self) -> None:
        with pytest.raises(ValueError, match="non-blank"):
            Credential("x", "   ")

    def test_legacy_agent_ids_outside_the_label_alphabet_still_work(self, mesh: CausalMesh) -> None:
        store = CredentialStore.from_config(agent_tokens={"my agent/é": OPERATOR})
        assert store.credentials()[0].label.startswith("agent-token:my_agent")

    def test_a_token_file_with_an_unknown_key_is_refused(self, tokens_path: Path) -> None:
        tokens_path.write_text("tokens: []\nsurprise: 1\n", encoding="utf-8")
        os.chmod(tokens_path, 0o600)
        with pytest.raises(ValueError, match="unknown top-level"):
            CredentialStore(tokens_file=tokens_path)

    def test_yaml_dates_and_naive_times_are_read_as_utc(self, tokens_path: Path) -> None:
        tokens_path.write_text(
            "tokens:\n  - {id: a, token: aaaaaaaaaaaaaaaaaaaa, expires: 2026-12-31T00:00:00Z}\n"
            "  - {id: b, token: bbbbbbbbbbbbbbbbbbbb, expires: 2026-12-31}\n",
            encoding="utf-8",
        )
        os.chmod(tokens_path, 0o600)
        first, second = CredentialStore(tokens_file=tokens_path).credentials()
        assert first.expires_at == second.expires_at == 1_798_675_200.0

    def test_more_than_two_live_tokens_for_an_agent_warns(
        self, tokens_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write(
            tokens_path,
            [_entry(f"a{i}", f"alice-token-{i:019d}", "alice") for i in range(3)],
        )
        with caplog.at_level(logging.WARNING):
            CredentialStore(tokens_file=tokens_path)
        assert "3 live tokens" in caplog.text
        assert "alice-token-" not in caplog.text
