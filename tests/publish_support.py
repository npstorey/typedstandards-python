"""Shared by the publish tests: a visibly fake token, the documents the vendored CLI signs for
them (``docs``, a session fixture in ``conftest.py``), and a fake host whose files start as the
template's ``host.json`` and ``host-policy.json`` at ``70bfd18`` (``fixtures/template-host*.json``).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from support import FIXTURES, SEED_VARIABLE, analysis_input, fresh_seed_b64, synthetic_notebook

import typedstandards as ts

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from github_stub import FakeGitHub, dumps  # noqa: E402

#: A visibly fake token: the fine-grained prefix, then text no real token has.
TOKEN = "github_pat_TESTONLY_fake_value_for_tests"
ORIGIN = "https://host-template.typedstandards.org"


@dataclass
class Docs:
    first: dict[str, Any]  # the record a host lists as "dog-licensing"
    second: dict[str, Any]  # a rerun: another envelopeHash
    blobref: dict[str, Any]  # output signed by reference
    foreign: dict[str, Any]  # signed under another key
    revises: dict[str, Any]  # attestation/revises/v1: target first, successor second
    withdrawal: dict[str, Any]  # attestation/withdraws/v1 of first
    corroboration: dict[str, Any]  # a claim-to-claim node on first
    signer: str
    note: dict[str, Any]  # the template's example entry, first-note, re-signed by the test key
    renamed: dict[str, Any]  # the test key, another signer.displayName
    supersedes: dict[str, Any]  # attestation/supersedes/v1: target first, successor second


def make_docs(directory: Path) -> Docs:
    """Sign the publish tests' documents through the vendored CLI under fresh seeds."""
    notebook = directory / "dog-licensing.ipynb"
    notebook.write_text(synthetic_notebook(), encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(SEED_VARIABLE, fresh_seed_b64())
        first = ts.sign(analysis_input(), output_file=notebook)
        second = ts.sign(analysis_input(), output_file=notebook)
        blobref = ts.sign(
            analysis_input(),
            output_file=notebook,
            output_url="https://files.example.org/dog-licensing.ipynb",
            content_type="application/x-ipynb+json",
        )
        signer = first["package"]["signer"]
        revises = ts.attest(
            {
                "type": "attestation/revises/v1",
                "targetNodeId": first["envelopeHash"],
                "successorNodeId": second["envelopeHash"],
                "signer": signer,
            }
        )
        withdrawal = ts.withdraw(
            {"targetNodeId": first["envelopeHash"], "reason": "A test withdrawal.", "signer": signer}
        )
        corroboration = ts.attest(
            {
                "type": "attestation/corroborates/v1",
                "targetNodeId": first["envelopeHash"],
                "scope": "the whole record",
                "signer": signer,
            }
        )
        supersedes = ts.attest(
            {
                "type": "attestation/supersedes/v1",
                "targetNodeId": first["envelopeHash"],
                "successorNodeId": second["envelopeHash"],
                "signer": signer,
            }
        )
        note = ts.sign(analysis_input(output="A first signed note."))
        renamed_signer = {"bindingTier": "pseudonymous", "displayName": "Another display name"}
        renamed = ts.sign(analysis_input(signer=renamed_signer), output_file=notebook)
        mp.setenv(SEED_VARIABLE, fresh_seed_b64())
        foreign = ts.sign(analysis_input(), output_file=notebook)
    return Docs(
        first,
        second,
        blobref,
        foreign,
        revises,
        withdrawal,
        corroboration,
        signer["identifier"],
        note,
        renamed,
        supersedes,
    )


def template_manifest() -> dict[str, Any]:
    return json.loads((FIXTURES / "template-host.json").read_text(encoding="utf-8"))


def template_policy(signer: str) -> dict[str, Any]:
    """The template's policy with this test's signer, and ``notebook`` in the active rule (P1)."""
    value = json.loads((FIXTURES / "template-host-policy.json").read_text(encoding="utf-8"))
    value["signer"] = signer
    value["display"][0]["extensions"]["role"].append("notebook")
    return value


def github(
    docs: Docs,
    *,
    listed: dict[str, dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> FakeGitHub:
    """A host with the template's files, plus each of ``listed`` (name to signed document)."""
    files = {
        "host.json": (FIXTURES / "template-host.json").read_bytes(),
        "host-policy.json": dumps(policy if policy is not None else template_policy(docs.signer)),
        # The template's example entry, its file re-signed by this test's key: a host serves one signer.
        "records/first-note.signed.json": dumps(docs.note),
    }
    value = manifest if manifest is not None else template_manifest()
    for name, signed in (listed or {}).items():
        path = f"records/{name}.signed.json"
        files[path] = dumps(signed)
        value["records"].append(
            {"name": name, "signed": path, "attestations": [], "title": name, "extensions": {"role": "notebook"}}
        )
    if listed or manifest is not None:
        files["host.json"] = dumps(value)
    return FakeGitHub(files, token=TOKEN)


def host(gh: FakeGitHub, **kwargs: Any) -> ts.GitHubPagesHost:
    return ts.GitHubPagesHost(gh.repository, token=TOKEN, transport=gh.transport(), **kwargs)
