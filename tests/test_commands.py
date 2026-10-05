"""The five pass-throughs end to end, the forms their inputs take, and the vendored tree."""

from __future__ import annotations

import hashlib  # test code only: checks what the CLI computed
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from support import self_certifying_input

import typedstandards

PACKAGE = Path(typedstandards.__file__).parent


def cli_calls(spawned: list[dict[str, Any]], command: str) -> list[dict[str, Any]]:
    entry = str(typedstandards.cli_entry())
    return [c for c in spawned if len(c["args"]) > 2 and c["args"][1] == entry and c["args"][2] == command]


def flag_values(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def test_sign_view_verify_round_trip(seed: str) -> None:
    signed = typedstandards.sign(self_certifying_input())
    assert set(signed) == {"package", "envelopeHash", "signature"}
    assert signed["package"]["signer"]["identifier"].startswith("did:key:z6Mk")
    bundle = typedstandards.view(signed, visibility="public", title="A test record")
    assert bundle["packageHash"] == signed["envelopeHash"]
    assert bundle["subjectTitle"] == "A test record"
    assert "trustRegistryUrl" not in bundle  # a self-certifying signer
    result = typedstandards.verify(bundle)
    assert result["ok"] is True
    assert result["lifecycle"]["status"] == "active"
    assert "checks" in result


def test_withdraw_carried_in_a_view(seed: str) -> None:
    signed = typedstandards.sign(self_certifying_input())
    withdrawal = typedstandards.withdraw(
        {"targetNodeId": signed["envelopeHash"], "reason": "a test withdrawal", "signer": signed["package"]["signer"]}
    )
    assert set(withdrawal) == {"node", "nodeId", "signature"}
    bundle = typedstandards.view(signed, visibility="public", attestations=[withdrawal])
    assert bundle["lifecycle"]["status"] == "withdrawn"
    assert typedstandards.verify(bundle)["lifecycle"]["status"] == "withdrawn"


def test_attest_signs_a_corroboration(seed: str) -> None:
    signed = typedstandards.sign(self_certifying_input())
    node = typedstandards.attest(
        {
            "type": "attestation/corroborates/v1",
            "targetNodeId": signed["envelopeHash"],
            "scope": "the whole record",
            "signer": {"bindingTier": "pseudonymous", "displayName": "Example corroborator"},
        }
    )
    assert node["node"]["type"] == "attestation/corroborates/v1"
    assert node["node"]["targetNodeId"] == signed["envelopeHash"]


def test_view_removes_its_temporary_files(seed: str, spawned: list[dict[str, Any]]) -> None:
    signed = typedstandards.sign(self_certifying_input())
    withdrawal = typedstandards.withdraw(
        {"targetNodeId": signed["envelopeHash"], "reason": "r", "signer": signed["package"]["signer"]}
    )
    typedstandards.view(signed, visibility="public", attestations=[withdrawal])
    (call,) = cli_calls(spawned, "view")
    files = flag_values(call["args"], "--signed") + flag_values(call["args"], "--attestation")
    assert len(files) == 2
    assert call["stdin"] is None
    for path in files:
        assert not Path(path).exists()


def test_view_removes_its_temporary_files_on_failure(seed: str, spawned: list[dict[str, Any]]) -> None:
    value = self_certifying_input()
    value["signer"] = {"bindingTier": "platform", "identifier": "platform:example", "displayName": "Example"}
    signed = typedstandards.sign(value)
    with pytest.raises(typedstandards.UsageError) as caught:
        typedstandards.view(signed, visibility="public")  # a non-did:key signer needs a registry URL
    assert "trustRegistryUrl" in caught.value.stderr
    (call,) = cli_calls(spawned, "view")
    assert not Path(flag_values(call["args"], "--signed")[0]).exists()


def test_view_passes_paths_as_given(seed: str, tmp_path: Path, spawned: list[dict[str, Any]]) -> None:
    signed_path = tmp_path / "signed.json"
    signed_path.write_text(json.dumps(typedstandards.sign(self_certifying_input())), encoding="utf-8")
    typedstandards.view(signed_path, visibility="unlisted", package_url="https://example.org/r.json")
    (call,) = cli_calls(spawned, "view")
    assert flag_values(call["args"], "--signed") == [str(signed_path)]
    assert flag_values(call["args"], "--visibility") == ["unlisted"]
    assert flag_values(call["args"], "--package-url") == ["https://example.org/r.json"]
    assert signed_path.exists()


def test_verify_without_full(seed: str, spawned: list[dict[str, Any]]) -> None:
    signed = typedstandards.sign(self_certifying_input())
    result = typedstandards.verify(signed, full=False)
    assert set(result) == {"ok", "nodeId", "failures"}
    (call,) = cli_calls(spawned, "verify")
    assert "--json" not in call["args"]


def test_sign_an_output_file_inline(seed: str, tmp_path: Path) -> None:
    output = tmp_path / "result.txt"
    output.write_text("forty-two\n", encoding="utf-8")
    value = self_certifying_input()
    value.pop("output", None)
    value.pop("contentCanonicalization", None)  # the golden input names legacy-json/v1
    signed = typedstandards.sign(value, output_file=output)
    assert signed["package"]["output"] == "forty-two\n"
    assert signed["package"]["contentHash"]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_mapping_input_goes_in_a_temporary_file(seed: str, spawned: list[dict[str, Any]]) -> None:
    value = self_certifying_input()
    typedstandards.sign(value)
    (call,) = cli_calls(spawned, "sign")
    (path,) = flag_values(call["args"], "--input")
    assert call["args"][3:] == ["--input", path]
    assert call["stdin"] is None
    assert json.loads(call["files"][path].decode("utf-8")) == value
    assert not Path(path).exists()


def test_success_diagnostics_are_logged(seed: str, caplog: pytest.LogCaptureFixture) -> None:
    """An attention reading the CLI prints on stderr with exit 0 is logged, not lost."""
    signed = typedstandards.sign(self_certifying_input())
    with caplog.at_level(logging.INFO, logger="typedstandards"):
        typedstandards.attest(
            {
                "type": "attestation/corroborates/v1",
                "targetNodeId": signed["envelopeHash"],
                "scope": "the whole record",
                "signer": {"bindingTier": "platform", "identifier": "platform:example", "displayName": "Example"},
            }
        )
    assert "authorization: key_unbound (attention)" in caplog.text


@pytest.mark.parametrize("bad", [42, b"{}", ["a"]])
def test_input_types(bad: Any) -> None:
    with pytest.raises(TypeError):
        typedstandards.sign(bad)


def test_attestations_must_be_a_list(seed: str) -> None:
    signed = typedstandards.sign(self_certifying_input())
    with pytest.raises(TypeError):
        typedstandards.view(signed, visibility="public", attestations={"node": {}})  # type: ignore[arg-type]


def test_runs_the_vendored_tree(seed: str, spawned: list[dict[str, Any]]) -> None:
    entry = typedstandards.cli_entry()
    assert entry.is_relative_to(PACKAGE / "_vendor" / "node_modules")
    typedstandards.sign(self_certifying_input())
    (call,) = cli_calls(spawned, "sign")
    assert call["args"][0] == typedstandards.locate_node()


def test_vendored_tree_carries_each_licence() -> None:
    vendor = PACKAGE / "_vendor"
    lock = json.loads((vendor / "package-lock.json").read_text(encoding="utf-8"))
    packages = [key for key in lock["packages"] if key]
    assert len(packages) == 6
    for key in packages:
        assert (vendor / key / "LICENSE").is_file(), key
    assert not (vendor / "node_modules" / ".bin").exists()


def test_import_loads_neither_p2_dependency() -> None:
    """httpx and PyYAML are declared for P2's helpers; importing the package loads neither."""
    code = "import sys, typedstandards; print(sorted(m for m in ('httpx', 'yaml') if m in sys.modules))"
    printed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert printed.strip() == "[]"
