"""Acceptance 4: the CLI's exit codes 1 to 4 map to four exception classes that share a base and
carry the exit code and the CLI's stderr text (packages/cli/src/errors.ts:3-14 in typedstandards).
Exits 1, 2 and 3 are driven through the real CLI; exit 4 through a stub named by the override,
since the real CLI exits 4 only on a bug.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from support import SEED_VARIABLE, self_certifying_input, write_stub

import typedstandards
from typedstandards import (
    NODE_OVERRIDE,
    CliError,
    InternalError,
    NodeLocatorError,
    SeedError,
    UsageError,
    VerificationError,
)


def test_the_classes_share_a_base() -> None:
    for cls in (VerificationError, UsageError, SeedError, InternalError):
        assert issubclass(cls, CliError)
    assert len({VerificationError, UsageError, SeedError, InternalError}) == 4
    assert not issubclass(NodeLocatorError, CliError)


def test_exit_1_a_tampered_record(seed: str) -> None:
    signed = typedstandards.sign(self_certifying_input())
    tampered = copy.deepcopy(signed)
    tampered["package"]["metadata"]["createdAt"] = "2000-01-01T00:00:00.000Z"
    with pytest.raises(VerificationError) as caught:
        typedstandards.verify(tampered)
    err = caught.value
    assert err.exit_code == 1
    assert "#1 envelopeIntegrity: altered (alarm)" in err.stderr
    # verify prints its verdict on stdout before exiting 1; the exception carries it.
    assert err.document["ok"] is False
    assert {"check": "#1", "field": "envelopeIntegrity", "status": "altered"} in err.document["failures"]
    assert "checks" in err.document  # --json, the default


def test_exit_2_a_bad_input(seed: str) -> None:
    bad = self_certifying_input()
    bad["notAField"] = True
    with pytest.raises(UsageError) as caught:
        typedstandards.sign(bad)
    assert caught.value.exit_code == 2
    assert "notAField" in caught.value.stderr
    assert caught.value.command == "sign"


def test_exit_3_an_unset_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SEED_VARIABLE, raising=False)
    with pytest.raises(SeedError) as caught:
        typedstandards.sign(self_certifying_input())
    assert caught.value.exit_code == 3
    assert f"{SEED_VARIABLE} is not set" in caught.value.stderr


def test_exit_3_a_malformed_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SEED_VARIABLE, "not a seed")
    with pytest.raises(SeedError) as caught:
        typedstandards.withdraw({"targetNodeId": "a" * 64, "reason": "r", "signer": {"bindingTier": "pseudonymous"}})
    assert caught.value.exit_code == 3


def test_exit_4_an_internal_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = write_stub(tmp_path, "node", "v24.21.0", exit_code=4, stderr="typedstandards sign: internal error: stub")
    monkeypatch.setenv(NODE_OVERRIDE, str(stub))
    with pytest.raises(InternalError) as caught:
        typedstandards.sign(self_certifying_input())
    assert caught.value.exit_code == 4
    assert caught.value.stderr == "typedstandards sign: internal error: stub\n"


def test_an_unmapped_exit_code_raises_the_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = write_stub(tmp_path, "node", "v24.21.0", exit_code=9, stderr="unexpected")
    monkeypatch.setenv(NODE_OVERRIDE, str(stub))
    with pytest.raises(CliError) as caught:
        typedstandards.sign(self_certifying_input())
    assert type(caught.value) is CliError
    assert caught.value.exit_code == 9
