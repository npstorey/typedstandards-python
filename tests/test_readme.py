"""The README is the wheel's long description, shown on PyPI, where a relative link does not
resolve. Every Markdown link and image in it is absolute (or an in-page ``#anchor``).

It also pins the README's Node sentence: only the five commands, ``cli_version()`` and ``show``
without a result run the CLI and so need Node; the other helpers run without one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from support import FIXTURES, synthetic_notebook

import typedstandards

README = Path(__file__).parent.parent / "README.md"

#: An inline link or image destination: ``](dest)`` or ``](<dest>)``; and a reference definition.
_INLINE = re.compile(r"\]\(\s*(<[^>]*>|[^)\s]+)")
_REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
_ABSOLUTE = re.compile(r"(https?://|mailto:|#)")


def relative_links(markdown: str) -> list[str]:
    """Every link or image destination outside fenced code that is neither absolute nor an anchor."""
    prose = re.sub(r"^```.*?^```", "", markdown, flags=re.MULTILINE | re.DOTALL)
    found = [m.strip("<>") for m in _INLINE.findall(prose)] + _REFERENCE.findall(prose)
    return [dest for dest in found if not _ABSOLUTE.match(dest)]


def test_the_checker_finds_relative_links() -> None:
    text = "See [a](CLAUDE.md), ![i](docs/x.png), [b](<rel path.md>), [c](#use), [d](https://x.org/y).\n\n[e]: e.md\n"
    assert relative_links(text) == ["CLAUDE.md", "docs/x.png", "rel path.md", "e.md"]


def test_readme_has_no_relative_link() -> None:
    assert relative_links(README.read_text(encoding="utf-8")) == []


def test_the_helpers_need_no_node(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(typedstandards.NODE_OVERRIDE, str(tmp_path / "no-node-here"))
    with pytest.raises(typedstandards.NodeLocatorError):
        typedstandards.locate_node()

    notebook = tmp_path / "analysis.ipynb"
    notebook.write_text(synthetic_notebook(), encoding="utf-8")
    typedstandards.badge_cell(
        "https://records.example.org/bundles/analysis.bundle.json", capture_method="script-run", notebook=notebook
    )
    typedstandards.comparison_cell(notebook, {"rows": 1}, recompute="recompute()", captured_at="2026-10-04T00:00:00Z")
    typedstandards.pin(
        "https://files.example.org/data.csv", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x"))
    )
    bundle = json.loads((FIXTURES / "record-active.bundle.json").read_text(encoding="utf-8"))
    result = json.loads((FIXTURES / "record-active.verify.json").read_text(encoding="utf-8"))
    typedstandards.sidecar(bundle, notebook)
    typedstandards.show(bundle, result)

    # The calls that run the CLI raise it, naming the floor and the override.
    for call in (
        lambda: typedstandards.show(bundle),
        lambda: typedstandards.verify(bundle),
        lambda: typedstandards.view(FIXTURES / "record-active.signed.json", visibility="public"),
        typedstandards.cli_version,
    ):
        with pytest.raises(typedstandards.NodeLocatorError, match="20.19"):
            call()
