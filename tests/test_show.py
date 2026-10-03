"""Acceptance 5: ``show``.

From the captured ``verify --json`` documents (``fixtures/record-*.verify.json``, with their
bundles) it renders the type and role, the abbreviated signer with "Signed with a
self-certifying key", the display name marked as the signer's own description, the first 12 hex
of the hash, ``createdAt``, ``vcsRef`` marked "asserted; not fetched", the status with its
reason or successor, one line per check, and the spec §9.3 sentence. Rendering needs no Node.
The Jupyter form has ``_repr_html_``; the Marimo form is ``mo.Html`` of the same HTML. The
output is byte-stable (``fixtures/show-*.html``). Every string from the record is escaped.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import types
from typing import Any

import pytest
from support import FIXTURES

from typedstandards import Shown, show
from typedstandards._show import KEY_DERIVED_MATCH_LABEL, NOT_CORRECTNESS, SELF_CERTIFIED_LABEL


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def pair(record: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return load(f"record-{record}.bundle.json"), load(f"record-{record}.verify.json")


def html_of(record: str) -> str:
    bundle, result = pair(record)
    return show(bundle, result).html


# --- what it renders ------------------------------------------------------------------------


@pytest.mark.parametrize("record", ["active", "withdrawn"])
def test_renders_the_record_and_its_checks(record: str) -> None:
    bundle, result = pair(record)
    package = bundle["package"]
    html = show(bundle, result).html
    identifier = package["signer"]["identifier"]

    assert "<code>content/analysis/v1</code>" in html
    role = package["extensions"]["role"]
    assert f'{role} <span style="color: #555;">(asserted by the signer in extensions[&quot;role&quot;]' in html
    abbreviated = f"did:key:{identifier[8:16]}…{identifier[-6:]}"
    assert f'<code title="{identifier}">{abbreviated}</code> · {SELF_CERTIFIED_LABEL}' in html
    assert "calls itself “Example analyst”" in html
    assert "(the signer’s own description; not verified)" in html
    assert f">{result['nodeId'][:12]}…</code>" in html
    assert f"<code>{package['metadata']['createdAt']}</code>" in html
    vcs = package["vcsRef"]
    assert (
        f"<code>{vcs['repoUrl']}</code>, commit <code>{vcs['commitSha']}</code>, path <code>{vcs['path']}</code>"
        in html
    )
    assert "(asserted; not fetched)" in html
    assert NOT_CORRECTNESS in html
    assert html.count(NOT_CORRECTNESS) == 1

    # One line per check verify-core reported, each numbered as spec §9.2 numbers it.
    lines = re.findall(r"<li>(#\d+) [^:<]+:", html)
    assert lines == ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8", "#9", "#10", "#11", "#12", "#14", "#15", "#16"]
    assert f"#14 Signer identity: {KEY_DERIVED_MATCH_LABEL}" in html
    assert f"#5 Key trust: {SELF_CERTIFIED_LABEL}" in html


def test_active_status() -> None:
    row = re.search(r">Status</th><td[^>]*>(.*?)</td>", html_of("active"))
    assert row is not None and row.group(1) == "<code>active</code>"


def test_a_withdrawn_record_renders_its_reason() -> None:
    bundle, result = pair("withdrawn")
    html = show(bundle, result).html
    reason = result["lifecycle"]["withdrawnReason"]
    assert reason == "The claim compared periods of different lengths; a restatement replaces it."
    assert f"<code>withdrawn</code>, reason: {reason}" in html
    assert "#10 Lifecycle: <code>withdrawn</code>" in html


def test_a_superseded_record_renders_its_successor() -> None:
    bundle, result = pair("active")
    successor = "f" * 64
    lifecycle = {"status": "superseded", "source": "attestation-chain", "chain": [], "successorNodeId": successor}
    result = {**result, "lifecycle": {**lifecycle, "supersededAt": "2026-10-04T09:00:00.000Z"}}
    html = show(bundle, result).html
    assert f'<code>superseded</code>, successor: <code title="{successor}">ffffffffffff…</code>' in html


def test_no_check_mark_and_no_person_claims() -> None:
    for record in ("active", "withdrawn"):
        html = html_of(record)
        for mark in ("✓", "✔", "☑", "✅", "&#10003;", "&check;"):
            assert mark not in html
        assert "same person" not in html and "same publisher" not in html
        assert "#14 Signer identity: <code>ok</code>" not in html


def test_a_registry_bound_signer_is_not_labelled_self_certifying() -> None:
    bundle, result = pair("active")
    result = copy.deepcopy(result)
    result["checks"]["keyTrust"] = {"status": "active", "verified": True, "kid": "example:key-1"}
    result["checks"]["signerIdentity"] = {"status": "ok"}
    html = show(bundle, result).html
    assert SELF_CERTIFIED_LABEL not in html
    assert "key status <code>active</code>" in html
    assert "#14 Signer identity: <code>ok</code>" in html


def test_a_failed_verdict_lists_its_failures() -> None:
    bundle, result = pair("active")
    result = {**result, "ok": False, "failures": ["content_hash_mismatch"]}
    html = show(bundle, result).html
    assert "<code>verify</code>: failed, <code>content_hash_mismatch</code>" in html


def test_role_path_reads_another_layout() -> None:
    bundle, result = pair("active")
    bundle = copy.deepcopy(bundle)
    bundle["package"]["extensions"] = {"org.example.notebook": {"role": ["analysis", "source"]}}
    html = show(bundle, result, role_path=("org.example.notebook", "role")).html
    assert "analysis, source <span" in html
    assert "none asserted in extensions[&quot;role&quot;]" in show(bundle, result).html


# --- byte-stable ------------------------------------------------------------------------------


@pytest.mark.parametrize("record", ["active", "withdrawn"])
def test_output_is_byte_stable(record: str) -> None:
    """Two renders are equal, and equal to the committed rendering of the same fixture."""
    first, second = html_of(record), html_of(record)
    assert first == second
    golden = (FIXTURES / f"show-{record}.html").read_bytes().decode("utf-8")
    assert first + "\n" == golden


def test_output_is_the_same_in_another_process() -> None:
    code = (
        "import json, sys; sys.path.insert(0, 'tests'); from support import FIXTURES; import typedstandards as t; "
        "b = json.loads((FIXTURES / 'record-withdrawn.bundle.json').read_text('utf-8')); "
        "r = json.loads((FIXTURES / 'record-withdrawn.verify.json').read_text('utf-8')); "
        "sys.stdout.buffer.write(t.show(b, r).html.encode('utf-8'))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True).stdout.decode("utf-8")
    assert hashlib.sha256(out.encode()).hexdigest() == hashlib.sha256(html_of("withdrawn").encode()).hexdigest()


# --- escaping -----------------------------------------------------------------------------------

SCRIPT = "<script>alert('x')</script>"


def _inject(where: str) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle, result = copy.deepcopy(pair("withdrawn"))
    package = bundle["package"]
    if where == "displayName":
        package["signer"]["displayName"] = SCRIPT
    elif where == "bindingTier":
        package["signer"]["bindingTier"] = SCRIPT
    elif where == "identifier":
        package["signer"]["identifier"] = "did:key:" + SCRIPT * 3
    elif where == "role":
        package["extensions"]["role"] = SCRIPT
    elif where == "summary":
        package["summary"] = SCRIPT
    elif where == "type":
        package["type"] = SCRIPT
    elif where == "vcsRef":
        package["vcsRef"] = {"repoUrl": SCRIPT, "commitSha": SCRIPT, "path": SCRIPT, "ref": SCRIPT}
    elif where == "createdAt":
        package["metadata"]["createdAt"] = SCRIPT
    elif where == "subjectTitle":
        bundle["subjectTitle"] = SCRIPT
    elif where == "withdrawnReason":
        result["lifecycle"]["withdrawnReason"] = SCRIPT
    elif where == "failures":
        result["ok"] = False
        result["failures"] = [SCRIPT]
    elif where == "check status":
        result["checks"]["contentProfile"]["status"] = SCRIPT
    elif where == "unknown check":
        result["checks"]["futureCheck"] = {"status": SCRIPT}
    return bundle, result


INJECTION_POINTS = [
    "displayName", "bindingTier", "identifier", "role", "summary", "type", "vcsRef", "createdAt",
    "subjectTitle", "withdrawnReason", "failures", "check status", "unknown check",
]  # fmt: skip


@pytest.mark.parametrize("where", INJECTION_POINTS)
def test_every_string_from_the_record_is_escaped(where: str) -> None:
    html = show(*_inject(where)).html
    assert "<script" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html


# --- Jupyter and Marimo -----------------------------------------------------------------------


def test_jupyter_form_has_repr_html() -> None:
    shown = show(*pair("active"))
    assert isinstance(shown, Shown)
    assert shown._repr_html_() == shown.html


def test_marimo_form_with_a_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    class Html:
        def __init__(self, text: str) -> None:
            self.text = text

    stand_in = types.ModuleType("marimo")
    stand_in.Html = Html  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "marimo", stand_in)
    shown = show(*pair("active"), marimo=True)
    assert isinstance(shown, Html)
    assert shown.text == html_of("active")


def test_marimo_form_with_marimo() -> None:
    import marimo as mo

    shown = show(*pair("withdrawn"), marimo=True)
    assert isinstance(shown, mo.Html)
    assert shown.text == html_of("withdrawn")


def test_without_a_result_show_asks_the_cli() -> None:
    bundle, result = pair("withdrawn")
    assert show(bundle).html == show(bundle, result).html


def test_without_a_result_a_record_that_fails_renders_its_failure() -> None:
    bundle, _ = pair("active")
    bundle = copy.deepcopy(bundle)
    bundle["package"]["output"] += " "
    html = show(bundle).html
    assert "<code>verify</code>: failed," in html


def test_paths_are_accepted() -> None:
    html = show(FIXTURES / "record-active.bundle.json", FIXTURES / "record-active.verify.json").html
    assert html == html_of("active")


def test_what_has_no_package_is_refused() -> None:
    with pytest.raises(ValueError, match="package inline"):
        show({"packageHash": "0" * 64}, {"ok": True})


def test_importing_the_package_loads_no_notebook_library() -> None:
    code = (
        "import sys, typedstandards; "
        "print(sorted(m for m in ('httpx', 'yaml', 'marimo', 'IPython', 'nbformat') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
