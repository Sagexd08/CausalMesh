"""TLS settings for `causalmesh serve`, checked before the socket is opened.

Uvicorn reports a bad certificate late and in its own words (or, for an
unreadable file, with a traceback). Every mistake here is an operator's, so
each is found first, named, and turned into a usage error.

The private key's passphrase is read from the environment, never from an
argument: an argument is visible in the process table, in shell history and
in `docker inspect`. Nothing in this module puts it in a message.
"""

from __future__ import annotations

import ipaddress
import os
import ssl
from pathlib import Path

__all__ = ["KEY_PASSWORD_ENV", "TlsConfigError", "is_loopback", "key_password", "validate_tls"]

KEY_PASSWORD_ENV = "CAUSALMESH_SSL_KEYFILE_PASSWORD"


class TlsConfigError(ValueError):
    """The TLS options are incomplete, unreadable or do not fit together."""


def is_loopback(host: str) -> bool:
    """Whether `host` is reachable only from this machine."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def key_password() -> str | None:
    """The key passphrase from `CAUSALMESH_SSL_KEYFILE_PASSWORD`, or None if unset/empty."""
    return os.environ.get(KEY_PASSWORD_ENV) or None


def _never_prompt() -> str:
    """Passphrase callback for a key that turned out to be encrypted, with none supplied.

    Without one, OpenSSL asks on the terminal, which hangs a service that has
    no terminal and hides the real problem.
    """
    raise TlsConfigError(
        f"the key is encrypted; set {KEY_PASSWORD_ENV} to its passphrase (it is never read "
        "from an argument)"
    )


def _readable(path: Path, what: str) -> None:
    if not path.exists():
        raise TlsConfigError(f"{what} does not exist: {path}")
    if not path.is_file():
        raise TlsConfigError(f"{what} is not a file: {path}")
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        raise TlsConfigError(
            f"{what} is not readable ({exc.strerror or type(exc).__name__}): {path}"
        ) from None


def validate_tls(certfile: Path | None, keyfile: Path | None, password: str | None) -> bool:
    """Check the TLS options; return whether TLS is on.

    Both or neither of certificate and key. When given, both must exist and
    be readable, and must load together (a key that does not match its
    certificate, a passphrase that is wrong or missing, and a file that is not
    PEM all fail here, not when the first client connects).
    """
    if certfile is None and keyfile is None:
        if password:
            raise TlsConfigError(
                f"{KEY_PASSWORD_ENV} is set but no --ssl-keyfile was given; nothing uses it"
            )
        return False
    if certfile is None or keyfile is None:
        missing = "--ssl-certfile" if certfile is None else "--ssl-keyfile"
        raise TlsConfigError(
            f"TLS needs both --ssl-certfile and --ssl-keyfile; {missing} is missing"
        )
    _readable(certfile, "--ssl-certfile")
    _readable(keyfile, "--ssl-keyfile")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(
            str(certfile), str(keyfile), password=password if password else _never_prompt
        )
    except TlsConfigError:
        raise
    except ssl.SSLError as exc:
        # `exc` carries OpenSSL's reason ("bad decrypt", "key values mismatch"),
        # which is the diagnosis and does not include the passphrase.
        raise TlsConfigError(
            f"the certificate and key could not be loaded together: {exc.reason or exc}. "
            f"Check they are PEM, that they match, and that {KEY_PASSWORD_ENV} holds the "
            "key's passphrase if it has one."
        ) from None
    except (OSError, ValueError, TypeError) as exc:
        raise TlsConfigError(
            f"the certificate and key could not be loaded: {type(exc).__name__}"
        ) from None
    return True
