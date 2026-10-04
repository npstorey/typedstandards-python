"""The captured record fixtures (``fixtures/capture_records.py``): each is pinned by SHA-256, and
each bundle's captured ``verify --json`` document is what the vendored CLI prints for it today."""

from __future__ import annotations

import hashlib
import json

import pytest
from support import FIXTURES

import typedstandards

PINNED = {
    "record-active.signed.json": "6a43fcbbd205a94ad71b94c7600b61c740177568b345af2744a947236285abfc",
    "record-active.bundle.json": "aa75bd9ad6f7c101ee2c3a96373e97826e6fae6dfa172bdc1e84bf69efcf5937",
    "record-active.verify.json": "a37890a4413b0ff206b0fc19f0cc998732c6b9590d504d5639b7ebbf3fccc833",
    "record-withdrawn.signed.json": "cbc91d561707f1e10034ff01a5cd587fb52276bae79f626665b14aa8d4bf5a9b",
    "record-withdrawn.withdrawal.json": "42bfe9b0ee86ba5b219c62a472a1d0e8ee45b5191fc7a7dd8cde842b69859a2e",
    "record-withdrawn.bundle.json": "33b608d24e36beca3314fde938513252380e2ffbeaff3312e4dcb4f58482d2eb",
    "record-withdrawn.verify.json": "8b882a0bc06300add88b5186b11861279a1f6505f80344d1c279aa1eaa3ad4ef",
}


@pytest.mark.parametrize("name", PINNED)
def test_fixture_is_the_captured_copy(name: str) -> None:
    assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == PINNED[name]


@pytest.mark.parametrize("record", ["active", "withdrawn"])
def test_captured_verify_is_what_the_cli_prints(record: str) -> None:
    bundle = json.loads((FIXTURES / f"record-{record}.bundle.json").read_text(encoding="utf-8"))
    captured = json.loads((FIXTURES / f"record-{record}.verify.json").read_text(encoding="utf-8"))
    assert typedstandards.verify(bundle) == captured
    assert captured["ok"] is True
    assert captured["lifecycle"]["status"] == record
