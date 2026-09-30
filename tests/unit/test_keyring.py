"""`load_key_ring`: the operator's trust input for `causalmesh verify --keys`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from causalmesh.crypto import KeyPair, KeyRingError, load_key_ring

pytestmark = pytest.mark.unit

SEED = b"keyring-seed-0123456789abcdef!!!"


def _pub(agent: str) -> str:
    return KeyPair.derive(SEED, agent).public_key_hex


def test_pub_files_load_and_are_normalized(tmp_path: Path) -> None:
    (tmp_path / "a.pub").write_text("  " + _pub("a").upper() + " \n", encoding="ascii")
    ring = load_key_ring(tmp_path)
    assert ring.keys == {"a": _pub("a")}


def test_a_seed_file_yields_its_public_key(tmp_path: Path) -> None:
    (tmp_path / "b.key").write_bytes(bytes(range(32)))
    expected = KeyPair.from_seed_file(tmp_path / "b.key", actor_id="b").public_key_hex
    assert load_key_ring(tmp_path).keys == {"b": expected}


def test_sources_can_be_mixed_and_agreeing_duplicates_are_fine(tmp_path: Path) -> None:
    (tmp_path / "a.pub").write_text(_pub("a"), encoding="ascii")
    (tmp_path / "keyring.json").write_text(json.dumps({"a": _pub("a"), "c": _pub("c")}))
    (tmp_path / "notes.txt").write_text("ignored")
    (tmp_path / "sub").mkdir()
    assert load_key_ring(tmp_path).keys == {"a": _pub("a"), "c": _pub("c")}


def test_disagreeing_sources_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a.pub").write_text(_pub("a"), encoding="ascii")
    (tmp_path / "keyring.json").write_text(json.dumps({"a": _pub("z")}))
    with pytest.raises(KeyRingError, match="different keys for 'a'"):
        load_key_ring(tmp_path)


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("a.pub", b"abcd", "64 hex characters"),
        ("a.pub", b"zz" * 32, "not hexadecimal"),
        ("a.key", b"short", "exactly 32 bytes"),
        ("keyring.json", b"[1, 2]", "JSON object"),
        ("keyring.json", b"{not json", "not a readable JSON"),
    ],
)
def test_malformed_material_is_refused_by_name(
    tmp_path: Path, name: str, content: bytes, message: str
) -> None:
    (tmp_path / name).write_bytes(content)
    with pytest.raises(KeyRingError, match=message):
        load_key_ring(tmp_path)


def test_an_empty_directory_and_a_missing_path_are_refused(tmp_path: Path) -> None:
    with pytest.raises(KeyRingError, match="holds no keys"):
        load_key_ring(tmp_path)
    with pytest.raises(KeyRingError, match="no key ring"):
        load_key_ring(tmp_path / "nope")


def test_a_single_json_file_is_a_ring(tmp_path: Path) -> None:
    path = tmp_path / "ring.json"
    path.write_text(json.dumps({"a": _pub("a")}))
    assert load_key_ring(path).keys == {"a": _pub("a")}
