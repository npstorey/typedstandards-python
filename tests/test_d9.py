"""Acceptance 5, second half (G0 D9 = A; typedstandards#136): verify drops a top-level
trustRegistry from a bundle before the CLI sees it, and changes nothing else.

CLI 0.2.0's verify accepts only the keys view prints (packages/cli/src/verify.ts:139-157), and
exits 2 on the trustRegistry that host-core 0.1.1 inlines in every bundle it serves under a
registry. The fixture is such a bundle, the host template's served first-note.bundle.json
(fixtures/README.md gives its provenance).
"""

from __future__ import annotations

import copy
import hashlib  # test code only: the fixture's provenance check
import json
from pathlib import Path
from typing import Any

import pytest
from support import BUNDLE_PATH, self_certifying_input

import typedstandards
from typedstandards._cli import run

BUNDLE_SHA256 = "cb11d2a229c9695db6c7f4d6c9349ccee14f14af6c39844886480699ba2401ba"


def bundle() -> dict[str, Any]:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


def cli_calls(spawned: list[dict[str, Any]], command: str) -> list[dict[str, Any]]:
    entry = str(typedstandards.cli_entry())
    return [c for c in spawned if len(c["args"]) > 2 and c["args"][1] == entry and c["args"][2] == command]


def test_fixture_is_the_pinned_copy() -> None:
    assert hashlib.sha256(BUNDLE_PATH.read_bytes()).hexdigest() == BUNDLE_SHA256
    assert "trustRegistry" in bundle()


def test_the_cli_itself_refuses_the_key() -> None:
    """The reason for the workaround. When a pinned CLI accepts the key this test fails, and the
    workaround and this test are removed together."""
    with pytest.raises(typedstandards.UsageError) as caught:
        run("verify", ["--input", str(BUNDLE_PATH)])
    assert "trustRegistry" in caught.value.stderr


def test_verify_drops_only_trust_registry(spawned: list[dict[str, Any]]) -> None:
    original = bundle()
    given = copy.deepcopy(original)
    result = typedstandards.verify(given)
    assert result["ok"] is True
    assert result["nodeId"] == original["packageHash"]
    assert given == original, "the caller's bundle was changed"
    (call,) = cli_calls(spawned, "verify")
    received = json.loads(call["stdin"].decode("utf-8"))
    expected = {k: v for k, v in original.items() if k != "trustRegistry"}
    assert received == expected
    assert list(received) == list(expected), "key order changed"


def test_verify_drops_it_from_a_path_too(spawned: list[dict[str, Any]]) -> None:
    result = typedstandards.verify(BUNDLE_PATH)
    assert result["ok"] is True
    (call,) = cli_calls(spawned, "verify")
    received = json.loads(call["stdin"].decode("utf-8"))
    assert received == {k: v for k, v in bundle().items() if k != "trustRegistry"}


def test_a_bundle_without_the_key_is_passed_as_given(seed: str, tmp_path: Path, spawned: list[dict[str, Any]]) -> None:
    view = typedstandards.view(typedstandards.sign(self_certifying_input()), visibility="public")
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(view), encoding="utf-8")
    spawned.clear()
    assert typedstandards.verify(path)["ok"] is True
    (call,) = cli_calls(spawned, "verify")
    assert call["args"][3:5] == ["--input", str(path)]
    assert call["stdin"] is None


def test_a_signed_document_is_not_altered(seed: str) -> None:
    """Only a bundle (a document with packageHash) loses the key; a signed document carrying it
    reaches the CLI as given, which refuses it."""
    signed = typedstandards.sign(self_certifying_input())
    signed["trustRegistry"] = {"keys": []}
    with pytest.raises(typedstandards.UsageError) as caught:
        typedstandards.verify(signed)
    assert "trustRegistry" in caught.value.stderr
