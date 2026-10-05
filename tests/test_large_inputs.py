"""No mapping input reaches the CLI through a pipe (npstorey/typedstandards-python#6).

CLI 0.2.0 reads ``--input -`` with a synchronous ``readFileSync(0)``, which fails with EAGAIN on a
piped document larger than a pipe buffer holds (npstorey/typedstandards#138): from Python on macOS
a 65,536-byte input failed, and on Linux a 692,380-byte one. So the wrapper writes every mapping
input to a temporary file, which it removes before it returns, and the child's standard input is
the null device. The documents here are over 2 MiB, above both measured thresholds.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from support import analysis_input, self_certifying_input

import typedstandards

#: Above both thresholds measured in typedstandards#138.
LARGE = 2 * 1024 * 1024


def cli_calls(spawned: list[dict[str, Any]], command: str) -> list[dict[str, Any]]:
    entry = str(typedstandards.cli_entry())
    return [c for c in spawned if len(c["args"]) > 2 and c["args"][1] == entry and c["args"][2] == command]


def flag_values(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def large_text() -> str:
    """Over 2 MiB of UTF-8 text with multi-byte characters."""
    lines = []
    size = 0
    number = 0
    while size <= LARGE:
        line = f"Résumé of row {number:07d}: café 実験 — 1.50\n"
        lines.append(line)
        size += len(line.encode("utf-8"))
        number += 1
    return "".join(lines)


def served_bundle(signed: dict[str, Any]) -> dict[str, Any]:
    """``view``'s output with a top-level trustRegistry inlined before ``package``, as host-core
    serves a bundle under a registry (the shape of fixtures/first-note.bundle.json). The key's
    fields are copied from what the CLI returned; nothing is computed here."""
    bundle = typedstandards.view(
        signed,
        visibility="public",
        title="A large test record",
        trust_registry_url="https://example.org/.well-known/typed-publisher.json",
    )
    key = signed["signature"]
    registry = {
        "$comment": "A test registry for one throwaway key.",
        "keys": [
            {
                "kid": key["kid"],
                "publicKey": key["publicKey"],
                "status": "active",
                "activatedAt": signed["package"]["metadata"]["createdAt"],
                "deprecatedAt": None,
                "revokedAt": None,
                "signerIdentity": signed["package"]["signer"],
            }
        ],
    }
    served: dict[str, Any] = {}
    for name, value in bundle.items():
        if name == "package":
            served["trustRegistry"] = registry
        served[name] = value
    return served


@pytest.fixture
def large_bundle(seed: str, tmp_path: Path) -> dict[str, Any]:
    """A served bundle over 2 MiB: a UTF-8 file over 2 MiB signed inline under a fresh seed."""
    output = tmp_path / "large.txt"
    output.write_text(large_text(), encoding="utf-8")
    assert output.stat().st_size > LARGE
    bundle = served_bundle(typedstandards.sign(analysis_input(), output_file=output))
    assert len(json.dumps(bundle, ensure_ascii=False).encode("utf-8")) > LARGE
    return bundle


def test_verify_a_large_served_bundle_as_a_mapping(large_bundle: dict[str, Any]) -> None:
    result = typedstandards.verify(large_bundle)
    assert result["ok"] is True
    assert result["nodeId"] == large_bundle["packageHash"]


def test_verify_a_large_served_bundle_as_a_path(large_bundle: dict[str, Any], tmp_path: Path) -> None:
    path = tmp_path / "large.bundle.json"
    path.write_text(json.dumps(large_bundle, ensure_ascii=False), encoding="utf-8")
    result = typedstandards.verify(path)
    assert result["ok"] is True
    assert result["nodeId"] == large_bundle["packageHash"]
    assert path.exists()


def test_sign_from_a_large_input_mapping(seed: str) -> None:
    text = large_text()
    value = analysis_input(output=text)
    assert len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > LARGE
    signed = typedstandards.sign(value)
    assert signed["package"]["output"] == text
    assert typedstandards.verify(signed)["ok"] is True


def assert_inputs_were_files(calls: list[dict[str, Any]]) -> None:
    """Each call's input reached the child as a file that existed when it started, the child's
    standard input was not a pipe, and every such file and its directory are gone now."""
    assert calls
    for call in calls:
        inputs = flag_values(call["args"], "--input")
        assert len(inputs) == 1, call["args"]
        (path,) = inputs
        assert path != "-", f"{call['args'][2]} got its input on standard input"
        assert call["kwargs"].get("stdin") is subprocess.DEVNULL, f"{call['args'][2]}'s stdin was not the null device"
        assert call["stdin"] is None
        assert path in call["files"], f"{path} was not a file when {call['args'][2]} started"
        assert not Path(path).exists(), f"{path} was left behind"
        assert not Path(path).parent.exists(), f"{Path(path).parent} was left behind"


def test_no_mapping_input_reaches_the_cli_on_a_pipe(seed: str, spawned: list[dict[str, Any]]) -> None:
    signed = typedstandards.sign(self_certifying_input())
    signer = signed["package"]["signer"]
    typedstandards.withdraw({"targetNodeId": signed["envelopeHash"], "reason": "r", "signer": signer})
    typedstandards.attest(
        {
            "type": "attestation/corroborates/v1",
            "targetNodeId": signed["envelopeHash"],
            "scope": "the whole record",
            "signer": {"bindingTier": "pseudonymous", "displayName": "Example corroborator"},
        }
    )
    assert typedstandards.verify(signed)["ok"] is True
    assert typedstandards.verify(served_bundle(signed))["ok"] is True
    for command, count in (("sign", 1), ("withdraw", 1), ("attest", 1), ("verify", 2)):
        calls = cli_calls(spawned, command)
        assert len(calls) == count, command
        assert_inputs_were_files(calls)
    # The signed document reached the CLI as given.
    first = cli_calls(spawned, "verify")[0]
    assert json.loads(first["files"][flag_values(first["args"], "--input")[0]]) == signed


def test_temporary_files_are_removed_when_the_cli_fails(seed: str, spawned: list[dict[str, Any]]) -> None:
    signed = typedstandards.sign(self_certifying_input())
    spawned.clear()
    with pytest.raises(typedstandards.UsageError):  # exit 2
        typedstandards.sign({"type": "content/analysis/v1"})
    with pytest.raises(typedstandards.UsageError):
        typedstandards.withdraw({"targetNodeId": signed["envelopeHash"]})
    with pytest.raises(typedstandards.UsageError):
        typedstandards.attest({"type": "attestation/corroborates/v1"})
    tampered = copy.deepcopy(signed)
    tampered["package"]["output"] = {"tampered": True}
    with pytest.raises(typedstandards.VerificationError) as caught:  # exit 1
        typedstandards.verify(tampered)
    assert caught.value.document["ok"] is False
    for command in ("sign", "withdraw", "attest", "verify"):
        assert_inputs_were_files(cli_calls(spawned, command))
