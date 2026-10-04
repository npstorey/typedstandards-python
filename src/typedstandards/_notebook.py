"""Insert one cell into a Jupyter notebook's ``cells``, keeping every other byte as written.

The notebook is read as JSON text, and the new cell is spliced into the ``cells`` array at its
start or its end. Nothing else is re-serialized, so key order, indentation, line endings, number
spelling and ``\\u`` escapes elsewhere in the file stay exactly as the author's tool wrote them.
The new cell itself is written in the file's own style: its indentation unit (nbformat writes 1),
its line ending, and ``ensure_ascii`` as found. Its keys are sorted, as nbformat writes them.

nbformat 4.5 (``nbformat_minor`` 5 or later) requires each cell to carry an ``id`` of 1 to 64
characters from ``[a-zA-Z0-9-_]``, unique in the notebook. The helpers give their cells fixed,
readable ids, so the same call on the same notebook writes the same bytes; an id already in the
notebook is refused, never replaced or suffixed. A notebook below 4.5 gets no ``id``, which its
schema does not allow.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

CELL_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}")
_WS = re.compile(r"[ \t\r\n]*")
_NON_ASCII_ESCAPE = re.compile(r"\\u(?:00[89a-fA-F][0-9a-fA-F]|0[1-9a-fA-F][0-9a-fA-F]{2}|[1-9a-fA-F][0-9a-fA-F]{3})")
_DECODER = json.JSONDecoder()


class _Layout:
    """Where ``cells`` and each of its elements sit in the notebook's text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.top_ws = ""  # whitespace between "{" and the first key
        self.first_value_ws = ""  # whitespace between the first key's ":" and its value
        self.first_item_ws: str | None = None  # whitespace after the "," that ends the first member
        self.cells_indent = ""  # the indentation of the line holding the "cells" key
        self.cells_open = -1  # index just after "["
        self.cells_close = -1  # index of "]"
        self.spans: list[tuple[int, int]] = []
        self._scan()

    def _ws(self, i: int) -> int:
        return _WS.match(self.text, i).end()  # type: ignore[union-attr]

    def _scan(self) -> None:
        text = self.text
        i = self._ws(0)
        if text[i : i + 1] != "{":
            raise ValueError("the notebook is not a JSON object")
        start = i + 1
        i = self._ws(start)
        self.top_ws = text[start:i]
        first = True
        while text[i : i + 1] != "}":
            key_start = i
            if text[i : i + 1] != '"':
                raise ValueError("the notebook's JSON is malformed")
            key, i = json.decoder.scanstring(text, i + 1)
            i = self._ws(i)
            if text[i : i + 1] != ":":
                raise ValueError("the notebook's JSON is malformed")
            colon = i + 1
            i = self._ws(colon)
            if first:
                self.first_value_ws = text[colon:i]
            if key == "cells":
                line_start = text.rfind("\n", 0, key_start) + 1
                self.cells_indent = text[line_start:key_start] if line_start else ""
                i = self._scan_cells(i)
            else:
                _, i = _DECODER.raw_decode(text, i)
            i = self._ws(i)
            if text[i : i + 1] == ",":
                after = self._ws(i + 1)
                if first:
                    self.first_item_ws = text[i + 1 : after]
                i = after
            first = False
        if self.cells_open < 0:
            raise ValueError("the notebook has no cells array")

    def _scan_cells(self, i: int) -> int:
        text = self.text
        if text[i : i + 1] != "[":
            raise ValueError("the notebook's cells is not an array")
        self.cells_open = i + 1
        i = self._ws(i + 1)
        while text[i : i + 1] != "]":
            start = i
            _, i = _DECODER.raw_decode(text, i)
            self.spans.append((start, i))
            i = self._ws(i)
            if text[i : i + 1] == ",":
                i = self._ws(i + 1)
        self.cells_close = i
        return i + 1


def _newline(layout: _Layout) -> str:
    return "\r\n" if "\r\n" in layout.text else "\n"


def _ensure_ascii(text: str) -> bool:
    """The file's ``ensure_ascii``: False when it holds a raw non-ASCII character, True when it
    escapes one as ``\\u....`` and holds none raw, and False (nbformat's choice) otherwise."""
    if any(ord(ch) > 0x7F for ch in text):
        return False
    return _NON_ASCII_ESCAPE.search(text) is not None


def _serialize(cell: dict[str, Any], layout: _Layout, base_indent: str) -> str:
    """The cell as JSON text in the file's style, its continuation lines indented by ``base_indent``."""
    ensure_ascii = _ensure_ascii(layout.text)
    if "\n" in layout.top_ws:
        unit = len(layout.top_ws.rsplit("\n", 1)[1])
        body = json.dumps(cell, indent=unit, ensure_ascii=ensure_ascii, sort_keys=True, separators=(",", ": "))
        return body.replace("\n", _newline(layout) + base_indent)
    item_sep = "," + (layout.first_item_ws or "")
    key_sep = ":" + layout.first_value_ws
    return json.dumps(cell, ensure_ascii=ensure_ascii, sort_keys=True, separators=(item_sep, key_sep))


def _indent_of(ws: str) -> str:
    return ws.rsplit("\n", 1)[1] if "\n" in ws else ""


def read_notebook(path: str | os.PathLike[str]) -> tuple[str, dict[str, Any]]:
    """The notebook's text and its parsed JSON; refuses anything but an nbformat 4 notebook."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{os.fspath(path)} starts with a UTF-8 byte-order mark, which nbformat does not write")
    text = raw.decode("utf-8")
    notebook = json.loads(text)
    if not isinstance(notebook, dict) or notebook.get("nbformat") != 4 or not isinstance(notebook.get("cells"), list):
        raise ValueError(f"{os.fspath(path)} is not an nbformat 4 notebook")
    return text, notebook


def insert_cell(
    path: str | os.PathLike[str],
    cell: dict[str, Any],
    *,
    where: Literal["first", "last"],
    cell_id: str,
) -> dict[str, Any]:
    """Splice ``cell`` into the notebook at ``path`` as its first or last cell; return the cell
    as written (with its ``id`` on nbformat 4.5 or later).

    Raises ``ValueError`` for a malformed ``cell_id``, or one another cell already has.
    """
    text, notebook = read_notebook(path)
    cell = dict(cell)
    if notebook.get("nbformat_minor", 0) >= 5:
        if not isinstance(cell_id, str) or CELL_ID.fullmatch(cell_id) is None:
            raise ValueError(f"cell id {cell_id!r} is not 1 to 64 characters of [a-zA-Z0-9-_] (nbformat 4.5)")
        taken = {c.get("id") for c in notebook["cells"] if isinstance(c, dict)}
        if cell_id in taken:
            raise ValueError(
                f"the notebook already has a cell with id {cell_id!r}; pass another cell_id, or remove that cell first"
            )
        cell["id"] = cell_id

    layout = _Layout(text)
    nl = _newline(layout)
    if layout.spans:
        lead = text[layout.cells_open : layout.spans[0][0]]
        base = _indent_of(lead)
        if len(layout.spans) > 1:
            sep = text[layout.spans[0][1] : layout.spans[1][0]]
        else:
            sep = "," + lead
        body = _serialize(cell, layout, base)
        if where == "first":
            at = layout.spans[0][0]
            new_text = text[:at] + body + sep + text[at:]
        else:
            at = layout.spans[-1][1]
            new_text = text[:at] + sep + body + text[at:]
    else:
        if "\n" in layout.top_ws:
            outer = layout.cells_indent if not layout.cells_indent.strip() else ""
            base = outer + _indent_of(layout.top_ws)
            body = nl + base + _serialize(cell, layout, base) + nl + outer
        else:
            body = _serialize(cell, layout, "")
        new_text = text[: layout.cells_open] + body + text[layout.cells_close :]

    expected = dict(notebook)
    expected["cells"] = [cell, *notebook["cells"]] if where == "first" else [*notebook["cells"], cell]
    if json.loads(new_text) != expected:  # pragma: no cover - a defect in the splice, never the input
        raise AssertionError("the spliced notebook does not parse to the notebook plus the new cell")
    Path(path).write_bytes(new_text.encode("utf-8"))
    return cell


def source_lines(text: str) -> list[str]:
    """``text`` as nbformat writes a cell's source: a list of lines, each keeping its newline."""
    return text.splitlines(keepends=True)
