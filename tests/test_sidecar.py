"""Acceptance 4: ``sidecar``.

It writes ``<artifact file name>.record.yaml`` from a real ``view`` of a signed fixture (the CLI
builds the view in the test) with the §8.8.1 field set, without ``package`` or ``trustRegistry``;
``yaml.safe_load`` of the file equals the JSON view on every field both express.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from support import BUNDLE_PATH, FIXTURES

import typedstandards
from typedstandards import sidecar
from typedstandards._sidecar import COMMITMENT_VIEW_FIELDS


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def active_view() -> dict[str, Any]:
    return typedstandards.view(load("record-active.signed.json"), visibility="public", title="Example analysis")


def withdrawn_view() -> dict[str, Any]:
    return typedstandards.view(
        load("record-withdrawn.signed.json"),
        visibility="public",
        attestations=[load("record-withdrawn.withdrawal.json")],
        title="Example claim",
    )


def _expected(view: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in view.items() if k not in {"package", "trustRegistry"}}


@pytest.mark.parametrize("make", [active_view, withdrawn_view], ids=["active", "withdrawn"])
def test_writes_the_commitment_view_fields(tmp_path: Path, make: Any) -> None:
    view = make()
    assert "package" in view  # what view prints: the §8.8.1 view plus the inline package
    path = sidecar(view, tmp_path / "analysis.ipynb")
    assert path == tmp_path / "analysis.ipynb.record.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert "package" not in loaded and "trustRegistry" not in loaded
    assert set(loaded) <= set(COMMITMENT_VIEW_FIELDS)
    # Every field view printed besides the two inlined ones, in view's order, equal to the JSON.
    assert list(loaded) == [k for k in view if k not in {"package", "trustRegistry"}]
    for key in loaded:
        assert loaded[key] == view[key], key
    assert loaded == _expected(view)


def test_the_withdrawn_view_keeps_its_lifecycle(tmp_path: Path) -> None:
    view = withdrawn_view()
    loaded = yaml.safe_load(sidecar(view, tmp_path / "claim.md").read_text(encoding="utf-8"))
    assert loaded["lifecycle"]["status"] == "withdrawn"
    assert loaded["lifecycleAttestations"] == view["lifecycleAttestations"]


def test_strings_stay_strings(tmp_path: Path) -> None:
    view = active_view()
    loaded = yaml.safe_load(sidecar(view, tmp_path / "analysis.ipynb").read_text(encoding="utf-8"))
    assert loaded["protocolVersion"] == "0.1.0"
    assert isinstance(loaded["protocolVersion"], str)
    assert isinstance(loaded["packageHash"], str)

    tricky = [
        "0.1.0", "1.0", "1e3", "0x1F", "0o17", "123", "-0", ".inf", "NaN", "yes", "no", "on", "off",
        "true", "False", "null", "~", "", "2026-10-03", "2026-10-03T12:30:00.000Z", "12:30:00", "1_000",
        "#comment", "key: value", "- item", "café 実験", " leading space", "line\nbreak",
    ]  # fmt: skip
    # At the top level, where a field such as subjectTitle is a bare string ...
    for i, value in enumerate(tricky):
        top = yaml.safe_load(sidecar({**view, "subjectTitle": value}, tmp_path / f"t{i}.ipynb").read_text("utf-8"))
        assert top["subjectTitle"] == value and type(top["subjectTitle"]) is str, repr(value)
    # ... and nested, in lists and as mapping keys.
    view = {**view, "subjectTitle": tricky, "subjectSummary": {t: t for t in tricky if t}}
    loaded = yaml.safe_load(sidecar(view, tmp_path / "tricky.ipynb").read_text(encoding="utf-8"))
    assert loaded["subjectTitle"] == tricky
    assert all(type(v) is str for v in loaded["subjectTitle"])
    assert loaded["subjectSummary"] == {t: t for t in tricky if t}


def test_unicode_is_written_as_text(tmp_path: Path) -> None:
    view = {**active_view(), "subjectTitle": "Café 実験"}
    text = sidecar(view, tmp_path / "analysis.ipynb").read_text(encoding="utf-8")
    assert "subjectTitle: Café 実験\n" in text


def test_a_served_bundle_drops_trust_registry(tmp_path: Path) -> None:
    """host-core's bundle (the template's, a P1 fixture) carries trustRegistry; the sidecar does not."""
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    assert "trustRegistry" in bundle and "package" in bundle
    loaded = yaml.safe_load(sidecar(BUNDLE_PATH, tmp_path / "first-note.md").read_text(encoding="utf-8"))
    assert loaded == _expected(bundle)
    assert "trustRegistry" not in loaded


def test_directory_places_the_file(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    path = sidecar(active_view(), "notebooks/analysis.ipynb", directory=out)
    assert path == out / "analysis.ipynb.record.yaml"
    assert path.is_file()


def test_what_sign_printed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="what view printed"):
        sidecar(load("record-active.signed.json"), tmp_path / "analysis.ipynb")
