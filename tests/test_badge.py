"""Acceptance 2: ``badge_cell``.

- The link and the Markdown equal what ``@typedstandards/host-core``'s own ``buildVerifyHref``
  and ``buildEmbedMarkdown`` print for the same URL (``fixtures/badge-golden.json``, captured
  from typedstandards ``116882a`` ``packages/host-core/src/links.ts``), and the percent-encoding
  equals the vendored Node's ``encodeURIComponent``, driven live.
- On a synthetic nbformat 4.5 notebook the badge is a markdown cell 0, and every other byte of
  the file is unchanged.
- The cell carries no 64-hex string and no date or time.
- The Marimo form is a cell's source that renders the same Markdown with ``mo.md``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

import nbformat
import pytest
from support import FIXTURES, synthetic_notebook

import typedstandards
from typedstandards import badge_cell
from typedstandards._badge import badge_markdown, encode_uri_component, verify_href

GOLDEN = FIXTURES / "badge-golden.json"
GOLDEN_SHA256 = "bd70f819249e8f8a5f3cf1245cbd521c32e3671623a4d3d6e009f71ae6661eaa"

#: npstorey/typedstandards-host-template README.md line 9 at 70bfd18: the badge host-core printed
#: for the template's served bundle.
TEMPLATE_README_LINE_9 = (
    "[![Verify this record with Typed Standards](https://typedstandards.org/badge/typed-standards-verify.svg)]"
    "(<https://typedstandards.org/verify?url=https%3A%2F%2Fhost-template.typedstandards.org%2Fbundles%2F"
    "first-note.bundle.json>)"
)

BUNDLE_URL = "https://records.example.org/bundles/analysis.bundle.json"
#: A URL holding every character encodeURIComponent leaves unescaped besides letters and digits.
UNESCAPED_SET_URL = "https://records.example.org/a-b_c.d!e~f*g'h(i)j/k.bundle.json"

HEX64 = re.compile(r"[0-9a-fA-F]{64}")
DATE_OR_TIME = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}")


def golden_cases() -> list[dict[str, str]]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


def test_golden_fixture_is_the_captured_copy() -> None:
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == GOLDEN_SHA256


# --- the link and the Markdown, against host-core ----------------------------------------------


@pytest.mark.parametrize("case", golden_cases(), ids=lambda c: c["url"][:60])
def test_link_and_markdown_equal_host_core(case: dict[str, str]) -> None:
    assert verify_href(case["url"]) == case["verify"]
    assert badge_markdown(case["url"]) == case["markdown"]


def test_template_readme_badge_is_reproduced() -> None:
    url = "https://host-template.typedstandards.org/bundles/first-note.bundle.json"
    assert badge_markdown(url) == TEMPLATE_README_LINE_9


def test_unescaped_set_is_left_as_is() -> None:
    href = verify_href(UNESCAPED_SET_URL)
    assert href.endswith("records.example.org%2Fa-b_c.d!e~f*g'h(i)j%2Fk.bundle.json")
    assert href == next(c["verify"] for c in golden_cases() if c["url"] == UNESCAPED_SET_URL)


ENCODING_PROBES = [
    UNESCAPED_SET_URL,
    "https://records.example.org/path with space/x.json?q=1&r=a+b#frag",
    "https://records.example.org/café/実験/\U0001f600/%41",
    'https://records.example.org/<>"[]{}|\\^`;/?:@&=+$,#',
    "".join(chr(c) for c in range(0x20, 0x7F)),
]


def test_encoding_equals_node_encode_uri_component() -> None:
    """Driven against a real encodeURIComponent: the Node that runs the CLI."""
    node = typedstandards.locate_node()
    script = (
        "let s='';process.stdin.on('data',d=>s+=d)"
        ".on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(encodeURIComponent))))"
    )
    proc = subprocess.run(
        [node, "-e", script], input=json.dumps(ENCODING_PROBES).encode(), capture_output=True, check=True
    )
    assert [encode_uri_component(p) for p in ENCODING_PROBES] == json.loads(proc.stdout)


def test_non_http_url_is_refused() -> None:
    with pytest.raises(ValueError, match="http"):
        verify_href("records.example.org/bundles/analysis.bundle.json")


# --- the Jupyter cell -------------------------------------------------------------------------


def _write(tmp_path: Path, text: str, name: str = "analysis.ipynb") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")  # read_text would translate CRLF


def _first_cell_offset(text: str) -> int:
    return text.index("{", text.index('"cells"'))


def test_badge_is_cell_0_and_every_other_byte_is_kept(tmp_path: Path) -> None:
    original = synthetic_notebook()
    path = _write(tmp_path, original)
    text = badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    written = _read(path)

    # Every byte before and after the inserted cell is the author's.
    at = _first_cell_offset(original)
    assert written.startswith(original[:at])
    assert written.endswith(original[at:])
    inserted = written[at : len(written) - len(original) + at]
    assert inserted.endswith(",\n  ")

    notebook = json.loads(written)
    before = json.loads(original)
    assert notebook["cells"][1:] == before["cells"]
    assert {k: v for k, v in notebook.items() if k != "cells"} == {k: v for k, v in before.items() if k != "cells"}
    cell = notebook["cells"][0]
    assert cell["cell_type"] == "markdown"
    assert cell["id"] == "typedstandards-badge"
    assert "".join(cell["source"]) == text
    assert text.splitlines()[0] == badge_markdown(BUNDLE_URL)
    assert text.splitlines()[0] == next(c["markdown"] for c in golden_cases() if c["url"] == BUNDLE_URL)
    assert "| Host | `records.example.org` |" in text
    assert "| Capture method | `script-run` |" in text
    nbformat.validate(nbformat.reads(written, as_version=nbformat.NO_CONVERT))


def test_inserted_cell_matches_nbformat_style(tmp_path: Path) -> None:
    """The new cell is written as nbformat would write it: nbformat's own writer, given the
    same notebook, gives the same bytes."""
    path = _write(tmp_path, synthetic_notebook())
    badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    written = _read(path)
    assert nbformat.writes(nbformat.reads(written, as_version=nbformat.NO_CONVERT)) + "\n" == written


def test_the_cell_names_no_hash_and_no_time(tmp_path: Path) -> None:
    path = _write(tmp_path, synthetic_notebook())
    text = badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    assert HEX64.search(text) is None
    assert DATE_OR_TIME.search(text) is None
    marimo = badge_cell(BUNDLE_URL, capture_method="script-run", marimo=True)
    assert HEX64.search(marimo) is None
    assert DATE_OR_TIME.search(marimo) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://records.example.org/bundles/" + "ab" * 32 + ".bundle.json",
        "https://records.example.org/2026-10-03/analysis.bundle.json",
    ],
    ids=["hash", "date"],
)
def test_a_url_carrying_a_hash_or_date_is_refused(tmp_path: Path, url: str) -> None:
    original = synthetic_notebook()
    path = _write(tmp_path, original)
    with pytest.raises(ValueError, match="written before signing"):
        badge_cell(url, capture_method="script-run", notebook=path)
    assert _read(path) == original


@pytest.mark.parametrize(
    "url",
    [
        "https://192.168.1.10:8080/bundles/a.bundle.json",
        "https://records.example.org:8443/a.bundle.json",
        "http://127.0.0.1:12345/bundles/a.bundle.json",
    ],
)
def test_a_host_with_a_port_is_not_read_as_a_time(tmp_path: Path, url: str) -> None:
    path = _write(tmp_path, synthetic_notebook())
    text = badge_cell(url, capture_method="script-run", notebook=path)
    assert text.splitlines()[0] == badge_markdown(url)
    assert json.loads(_read(path))["cells"][0]["id"] == "typedstandards-badge"


@pytest.mark.parametrize(
    ("url", "capture_method"),
    [
        ("https://192.168.1.10:8080/2026-10-04/a.bundle.json", "script-run"),
        ("https://records.example.org:8443/a.bundle.json?t=12:30", "script-run"),
        ("https://records.example.org/a.bundle.json?t=12%3A30%3A45", "script-run"),
        ("https://records.example.org/a.bundle.json#T12:30", "script-run"),
        ("https://192.168.1.10:8080/a.bundle.json", "run-T12:30:45"),
    ],
    ids=["date-in-path", "time-in-query", "encoded-time-in-query", "time-in-fragment", "time-in-fact"],
)
def test_a_date_or_time_beside_a_port_is_still_refused(url: str, capture_method: str) -> None:
    with pytest.raises(ValueError, match="date or time"):
        badge_cell(url, capture_method=capture_method)


def test_a_second_badge_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, synthetic_notebook())
    badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    once = path.read_bytes()
    with pytest.raises(ValueError, match="already has a cell with id 'typedstandards-badge'"):
        badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    assert path.read_bytes() == once


def test_same_call_same_bytes(tmp_path: Path) -> None:
    first, second = _write(tmp_path, synthetic_notebook(), "a.ipynb"), _write(tmp_path, synthetic_notebook(), "b.ipynb")
    badge_cell(BUNDLE_URL, capture_method="script-run", notebook=first)
    badge_cell(BUNDLE_URL, capture_method="script-run", notebook=second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("bad", ["", "has space", "x" * 65, "dot.ted"])
def test_a_malformed_cell_id_is_refused(tmp_path: Path, bad: str) -> None:
    path = _write(tmp_path, synthetic_notebook())
    with pytest.raises(ValueError, match="1 to 64 characters"):
        badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path, cell_id=bad)


@pytest.mark.parametrize("fact", ["host", "capture_method"])
def test_a_fact_that_would_break_the_table_is_refused(fact: str) -> None:
    kwargs = {"capture_method": "script-run", fact: "a | b"}
    with pytest.raises(ValueError, match=fact):
        badge_cell(BUNDLE_URL, **kwargs)


STYLES = {
    "indent-2": {"indent": 2},
    "indent-0": {"indent": 0},
    "compact": {"indent": None},
    "crlf": {"newline": "\r\n"},
    "ensure-ascii": {"ensure_ascii": True},
    "nbformat-4.4": {"minor": 4},
    "no-cells": {"cells": []},
}


@pytest.mark.parametrize("style", STYLES.values(), ids=STYLES.keys())
def test_other_styles_keep_their_bytes_and_stay_valid(tmp_path: Path, style: dict) -> None:
    original = synthetic_notebook(**style)
    path = _write(tmp_path, original)
    badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    written = _read(path)
    notebook = json.loads(written)
    assert notebook["cells"][1:] == json.loads(original)["cells"]
    if style.get("minor", 5) < 5:
        assert "id" not in notebook["cells"][0]
    else:
        assert notebook["cells"][0]["id"] == "typedstandards-badge"
    if json.loads(original)["cells"]:
        at = _first_cell_offset(original)
        assert written.startswith(original[:at]) and written.endswith(original[at:])
    nbformat.validate(nbformat.reads(written, as_version=nbformat.NO_CONVERT))
    # The file's own style is the inserted cell's: re-serialising the result in that style
    # reproduces it byte for byte.
    newline = style.get("newline", "\n")
    indent = style.get("indent", 1)
    if indent is None:
        again = json.dumps(notebook, sort_keys=True, ensure_ascii=style.get("ensure_ascii", False))
    else:
        again = json.dumps(
            notebook,
            sort_keys=True,
            indent=indent,
            ensure_ascii=style.get("ensure_ascii", False),
            separators=(",", ": "),
        )
        again = (again + "\n").replace("\n", newline)
    assert again == written


def test_unusual_bytes_elsewhere_survive(tmp_path: Path) -> None:
    """Unsorted keys, a number spelled 1.50E0 and an escaped slash are not re-serialised."""
    original = synthetic_notebook().replace(
        '   "language": "python",\n', '   "language": "python",\n   "z": 1.50E0,\n   "s": "a\\/b",\n', 1
    )
    assert '"z": 1.50E0' in original
    path = _write(tmp_path, original)
    badge_cell(BUNDLE_URL, capture_method="script-run", notebook=path)
    written = _read(path)
    at = _first_cell_offset(original)
    assert written.startswith(original[:at]) and written.endswith(original[at:])
    assert '"z": 1.50E0,\n   "s": "a\\/b",' in written


# --- the Marimo form ----------------------------------------------------------------------------


def _md_argument(source: str) -> str:
    call = ast.parse(source).body[0].value  # type: ignore[attr-defined]
    assert isinstance(call, ast.Call) and ast.unparse(call.func) == "mo.md"
    return ast.literal_eval(call.args[0])


def test_marimo_form_is_an_md_cell_with_the_same_badge() -> None:
    source = badge_cell(BUNDLE_URL, capture_method="script-run", marimo=True)
    assert source.startswith("mo.md(")
    assert _md_argument(source) == badge_cell(BUNDLE_URL, capture_method="script-run")
    assert _md_argument(source).splitlines()[0] == badge_markdown(BUNDLE_URL)


def test_marimo_renders_the_link() -> None:
    """Driven against marimo itself: its Markdown renders the angle-bracket destination as the link."""
    import marimo as mo

    source = badge_cell(BUNDLE_URL, capture_method="script-run", marimo=True)
    html = eval(compile(source, "<badge>", "eval"), {"mo": mo}).text  # noqa: S307 - our own generated source
    assert f'href="{verify_href(BUNDLE_URL)}"' in html
    assert 'src="https://typedstandards.org/badge/typed-standards-verify.svg"' in html


def test_marimo_form_refuses_a_notebook(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="marimo"):
        badge_cell(BUNDLE_URL, capture_method="script-run", marimo=True, notebook=tmp_path / "x.ipynb")
