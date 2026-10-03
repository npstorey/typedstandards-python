"""Acceptance 1: the golden's 9 envelope cases and its withdraws case replay through the
wrapper's sign and withdraw, and match serializedJson, contentHashSha256 and envelopeHash
(nodeId for the withdrawal).

The fixture is a verbatim copy of typedstandards' reference golden (fixtures/README.md gives its
provenance); the first test pins its SHA-256. The seed does not enter the envelope hash, so each
case is signed with a fresh test seed, except v01-self-certified-signer: its signer is the did:key
of RFC 8032 §7.1 TEST 1, and sign verifies its own result, so only that test vector's seed signs it.
"""

from __future__ import annotations

import hashlib  # test code only: the fixture's provenance check
import json
from typing import Any

import pytest
from support import GOLDEN_PATH, SEED_VARIABLE, fresh_seed_b64, load_golden, rfc8032_test_1_b64

import typedstandards

GOLDEN_SHA256 = "d2bcfc2bc017b07502b3b00c3aa16de402df134128a374b4582650b79fb501c1"
SELF_CERTIFIED = "v01-self-certified-signer"
GOLDEN = load_golden()


def serialized(value: Any) -> str:
    # JSON.stringify's form: no whitespace, non-ASCII kept.
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def test_fixture_is_the_pinned_copy() -> None:
    assert hashlib.sha256(GOLDEN_PATH.read_bytes()).hexdigest() == GOLDEN_SHA256


def test_fixture_holds_the_replayed_cases() -> None:
    assert len(GOLDEN["envelopeCases"]) == 9
    assert len(GOLDEN["attestationCases"]) == 6
    assert any(c["name"] == SELF_CERTIFIED for c in GOLDEN["envelopeCases"])
    assert any(c["name"] == "withdraws" for c in GOLDEN["attestationCases"])


@pytest.mark.parametrize("case", GOLDEN["envelopeCases"], ids=lambda c: c["name"])
def test_sign_replays_the_golden(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seed = rfc8032_test_1_b64() if case["name"] == SELF_CERTIFIED else fresh_seed_b64()
    monkeypatch.setenv(SEED_VARIABLE, seed)
    printed = typedstandards.sign(case["input"])
    expected = case["expected"]
    assert serialized(printed["package"]) == expected["serializedJson"], "serialized JSON diverged"
    if expected["contentHashSha256"] is None:
        assert "contentHash" not in printed["package"], "a legacy case carries no contentHash"
    else:
        assert printed["package"]["contentHash"]["sha256"] == expected["contentHashSha256"]
    assert printed["envelopeHash"] == expected["envelopeHash"], "envelope hash diverged"


def test_withdraw_replays_the_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    case = next(c for c in GOLDEN["attestationCases"] if c["name"] == "withdraws")
    monkeypatch.setenv(SEED_VARIABLE, fresh_seed_b64())
    printed = typedstandards.withdraw(case["input"])
    expected = case["expected"]
    assert serialized(printed["node"]) == expected["serializedJson"], "serialized JSON diverged"
    assert printed["node"]["contentHash"]["sha256"] == expected["contentHashSha256"]
    assert printed["nodeId"] == expected["nodeId"], "node id diverged"


def test_sign_replays_from_a_path(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same replay with the input given as a file path rather than a mapping."""
    case = next(c for c in GOLDEN["envelopeCases"] if c["name"] == "v01-default")
    path = tmp_path / "input.json"
    path.write_text(json.dumps(case["input"]), encoding="utf-8")
    monkeypatch.setenv(SEED_VARIABLE, fresh_seed_b64())
    printed = typedstandards.sign(path)
    assert serialized(printed["package"]) == case["expected"]["serializedJson"]
    assert printed["envelopeHash"] == case["expected"]["envelopeHash"]


def test_self_certified_case_needs_the_test_vector_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another seed cannot sign the self-certified case: sign's own check fails (exit 1),
    and nothing is printed on stdout."""
    case = next(c for c in GOLDEN["envelopeCases"] if c["name"] == SELF_CERTIFIED)
    monkeypatch.setenv(SEED_VARIABLE, fresh_seed_b64())
    with pytest.raises(typedstandards.VerificationError) as caught:
        typedstandards.sign(case["input"])
    assert caught.value.exit_code == 1
    assert caught.value.document is None
