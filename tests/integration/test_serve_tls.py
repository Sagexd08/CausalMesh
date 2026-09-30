"""`causalmesh serve` over TLS, checked with a real certificate and a real HTTPS request.

The certificate is generated here with `cryptography` (already a dependency)
and trusted explicitly by the client, so a passing test means the handshake
verified the server's certificate, not that verification was switched off.
"""

from __future__ import annotations

import secrets
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from causalmesh.server.tls import KEY_PASSWORD_ENV, TlsConfigError, is_loopback, validate_tls
from serve_process import ServeProcess, run_to_exit
from tls_certs import make_cert

pytestmark = [pytest.mark.integration]

CONTRACT = "version: 1\nroles: []\npolicy:\n  arm: C3\nevidence:\n  sign: false\n"
TOKEN = "tls-test-token-0123456789abcdef"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    return tmp_path


class TestHttpsEndToEnd:
    def test_a_real_https_request_verifies_the_certificate(self, root: Path) -> None:
        cert, key = make_cert(root)
        with ServeProcess(
            root,
            "--api-token",
            TOKEN,
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            tls_ca=cert,
        ) as server:
            status, _, body = server.request("GET", "/readyz")
            assert (status, body) == (200, {"status": "ready"})
            status, _, body = server.request("GET", "/v1/tools", token=TOKEN)
            assert status == 200
            assert server.request("GET", "/v1/tools")[0] == 401
        output = server.stop()
        assert "https://127.0.0.1" in output
        assert TOKEN not in output

    def test_plain_http_to_a_tls_port_is_not_served(self, root: Path) -> None:
        cert, key = make_cert(root)
        with ServeProcess(
            root,
            "--api-token",
            TOKEN,
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            tls_ca=cert,
        ) as server:
            plain = f"http://127.0.0.1:{server.port}/health"
            with pytest.raises((urllib.error.URLError, OSError, ConnectionError)):
                urllib.request.urlopen(plain, timeout=5)  # noqa: S310

    def test_a_client_that_does_not_trust_the_certificate_is_refused(self, root: Path) -> None:
        cert, key = make_cert(root)
        with ServeProcess(
            root,
            "--api-token",
            TOKEN,
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            tls_ca=cert,
        ) as server:
            with pytest.raises(urllib.error.URLError) as info:
                urllib.request.urlopen(  # noqa: S310
                    server.base + "/health", timeout=5, context=ssl.create_default_context()
                )
            assert isinstance(info.value.reason, ssl.SSLCertVerificationError)

    def test_an_encrypted_key_is_opened_with_the_passphrase_from_the_environment(
        self, root: Path
    ) -> None:
        passphrase = "correct horse battery staple"
        cert, key = make_cert(root, password=passphrase.encode())
        with ServeProcess(
            root,
            "--api-token",
            TOKEN,
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            tls_ca=cert,
            env={KEY_PASSWORD_ENV: passphrase},
        ) as server:
            assert server.request("GET", "/readyz")[0] == 200
        assert passphrase not in server.stop()

    def test_the_tls_files_can_come_from_the_environment(self, root: Path) -> None:
        cert, key = make_cert(root)
        with ServeProcess(
            root,
            "--api-token",
            TOKEN,
            tls_ca=cert,
            env={"CAUSALMESH_SSL_CERTFILE": str(cert), "CAUSALMESH_SSL_KEYFILE": str(key)},
        ) as server:
            assert server.request("GET", "/health")[0] == 200


class TestTlsRefusals:
    """Every mistake is a usage error naming the fix, before a socket is opened."""

    def _run(self, root: Path, *args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
        return run_to_exit(root, "--api-token", TOKEN, *args, env=env)

    def test_a_certificate_without_a_key(self, root: Path) -> None:
        cert, _ = make_cert(root)
        code, output = self._run(root, "--ssl-certfile", str(cert))
        assert code == 2
        assert "--ssl-keyfile" in output

    def test_a_key_without_a_certificate(self, root: Path) -> None:
        _, key = make_cert(root)
        code, output = self._run(root, "--ssl-keyfile", str(key))
        assert code == 2
        assert "--ssl-certfile" in output

    def test_a_missing_file(self, root: Path) -> None:
        _, key = make_cert(root)
        code, output = self._run(
            root, "--ssl-certfile", str(root / "nope.crt"), "--ssl-keyfile", str(key)
        )
        assert code == 2
        assert "does not exist" in output
        assert "Traceback" not in output

    def test_a_key_that_does_not_match_the_certificate(self, root: Path) -> None:
        cert, _ = make_cert(root, name="a")
        _, other_key = make_cert(root, name="b")
        code, output = self._run(root, "--ssl-certfile", str(cert), "--ssl-keyfile", str(other_key))
        assert code == 2
        assert "could not be loaded" in output
        assert "Traceback" not in output

    def test_garbage_in_place_of_pem(self, root: Path) -> None:
        cert, key = make_cert(root)
        key.write_text("this is not a key", encoding="utf-8")
        code, output = self._run(root, "--ssl-certfile", str(cert), "--ssl-keyfile", str(key))
        assert code == 2
        assert "Traceback" not in output

    def test_an_encrypted_key_without_a_passphrase_never_prompts(self, root: Path) -> None:
        cert, key = make_cert(root, password=secrets.token_hex(8).encode())
        code, output = self._run(root, "--ssl-certfile", str(cert), "--ssl-keyfile", str(key))
        assert code == 2
        assert KEY_PASSWORD_ENV in output

    def test_a_wrong_passphrase_is_refused_and_not_echoed(self, root: Path) -> None:
        right, wrong = secrets.token_hex(8), secrets.token_hex(8)
        cert, key = make_cert(root, password=right.encode())
        code, output = self._run(
            root,
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            env={KEY_PASSWORD_ENV: wrong},
        )
        assert code == 2
        assert wrong not in output
        assert right not in output

    def test_a_passphrase_with_nothing_to_open_is_a_mistake_not_ignored(self, root: Path) -> None:
        code, output = self._run(root, env={KEY_PASSWORD_ENV: "orphan"})
        assert code == 2
        assert "orphan" not in output


class TestRequireTls:
    def test_it_refuses_a_public_interface_without_tls(self, root: Path) -> None:
        code, output = run_to_exit(root, "--api-token", TOKEN, "--host", "0.0.0.0", "--require-tls")
        assert code == 2
        assert "--require-tls" in output
        assert TOKEN not in output

    def test_it_can_be_set_from_the_environment(self, root: Path) -> None:
        code, _ = run_to_exit(
            root,
            "--api-token",
            TOKEN,
            "--host",
            "0.0.0.0",
            env={"CAUSALMESH_REQUIRE_TLS": "1"},
        )
        assert code == 2

    def test_it_allows_a_public_interface_with_tls(self, root: Path) -> None:
        cert, key = make_cert(root)
        server = ServeProcess(
            root,
            "--api-token",
            TOKEN,
            "--host",
            "0.0.0.0",
            "--require-tls",
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            tls_ca=cert,
        )
        with server:
            assert server.request("GET", "/health")[0] == 200

    def test_it_does_not_get_in_the_way_of_localhost(self, root: Path) -> None:
        with ServeProcess(root, "--api-token", TOKEN, "--require-tls") as server:
            assert server.request("GET", "/health")[0] == 200


class TestPlainHttpWarning:
    def test_a_public_interface_without_tls_warns_clearly(self, root: Path) -> None:
        with ServeProcess(root, "--api-token", TOKEN, "--host", "0.0.0.0") as server:
            assert server.request("GET", "/health")[0] == 200
        output = server.stop()
        assert "plain HTTP" in output
        assert "--require-tls" in output
        assert TOKEN not in output

    def test_localhost_does_not_warn(self, root: Path) -> None:
        with ServeProcess(root, "--api-token", TOKEN) as server:
            assert server.request("GET", "/health")[0] == 200
        assert "plain HTTP" not in server.stop()


class TestValidateTlsUnit:
    def test_neither_option_is_not_an_error_and_means_no_tls(self) -> None:
        assert validate_tls(None, None, None) is False

    def test_the_key_must_be_readable(self, tmp_path: Path) -> None:
        cert, key = make_cert(tmp_path)
        directory = tmp_path / "adir"
        directory.mkdir()
        with pytest.raises(TlsConfigError, match="not a file"):
            validate_tls(cert, directory, None)
        assert validate_tls(cert, key, None) is True

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("127.0.0.1", True),
            ("127.0.0.2", True),
            ("localhost", True),
            ("LOCALHOST", True),
            ("::1", True),
            ("0.0.0.0", False),
            ("::", False),
            ("192.168.1.10", False),
            ("example.com", False),
        ],
    )
    def test_loopback_detection(self, host: str, expected: bool) -> None:
        assert is_loopback(host) is expected
