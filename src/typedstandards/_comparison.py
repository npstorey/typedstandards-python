"""``comparison_cell``: the spec §8.7.4 comparison cell, appended as a notebook's last cell.

The cell embeds the values an execution produced as Python literals, recomputes them with the
caller's expression, and prints each delta, in the canonical shape of spec §8.7.4 (the hub's
``docs/architecture/typed-standards-specification.md``, lines 860-874 at ``6957a3a``)::

    # ORIGINAL VALUES (captured at executedAt = <ISO-8601 timestamp>)
    original = {
        "<metric-name>": <literal value>,
    }

    # CURRENT VALUES (re-computed against live data using the same helpers + queries above)
    current = <the caller's recompute expression>

    # DELTAS
    for k in original:
        delta = ...
        print(...)

The spec's block indents by one space; the cell indents by four, as Python code usually is. The
cell is appended before signing, so it is inside the signed bytes.
"""

from __future__ import annotations

import ast
import json
import math
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ._notebook import insert_cell, source_lines

#: The comparison cell's id (nbformat 4.5).
COMPARISON_CELL_ID = "typedstandards-comparison"

_CURRENT_COMMENT = "# CURRENT VALUES (re-computed against live data using the same helpers + queries above)"
_DELTAS = (
    "# DELTAS\n"
    "for k in original:\n"
    "    delta = (current[k] - original[k]) if isinstance(original[k], (int, float)) else (original[k], current[k])\n"
    '    print(f"{k}: original={original[k]}, current={current[k]}, delta={delta}")\n'
)


def _string(value: str, where: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as err:
        raise ValueError(f"{where} is a string that is not valid UTF-8 text") from err
    return json.dumps(value, ensure_ascii=False)  # a JSON string is also a Python string literal


def literal(value: Any, where: str = "value") -> str:
    """``value`` as Python literal source. Admits ``None``, ``bool``, ``int``, finite ``float``,
    ``str``, and lists and str-keyed dicts of those; a subclass of ``int``, ``float`` or ``str``
    (a NumPy float, an ``IntEnum``) is written as its base value. Anything else raises
    ``TypeError``, and a non-finite float ``ValueError``."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return repr(int(value))
    if isinstance(value, float):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{where} is {number!r}, which has no Python literal")
        return repr(number)
    if isinstance(value, str):
        return _string(str(value), where)
    if type(value) is list:
        return "[" + ", ".join(literal(item, f"{where}[{i}]") for i, item in enumerate(value)) + "]"
    if type(value) is dict:
        parts = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{where} has a key {key!r} that is not a string")
            parts.append(f"{_string(str(key), where)}: {literal(item, f'{where}[{key!r}]')}")
        return "{" + ", ".join(parts) + "}"
    raise TypeError(
        f"{where} is a {type(value).__name__}, not a literal: comparison values are None, bool, int, float, "
        "str, or lists and str-keyed dicts of those"
    )


def _captured_at(value: str | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise ValueError("captured_at must be an ISO 8601 timestamp on one line")
    try:
        datetime.fromisoformat(value)
    except ValueError as err:
        raise ValueError(f"captured_at {value!r} is not an ISO 8601 timestamp") from err
    return value


def _recompute(expression: str) -> str:
    if not isinstance(expression, str) or not expression.strip() or "\n" in expression or "\r" in expression:
        raise ValueError("recompute must be one line of Python: an expression that returns the current values")
    try:
        ast.parse(expression, mode="eval")
    except SyntaxError as err:
        raise ValueError(f"recompute {expression!r} is not a Python expression") from err
    return expression.strip()


def comparison_source(values: Mapping[str, Any], *, recompute: str, captured_at: str | datetime) -> str:
    """The comparison cell's source, without writing it anywhere."""
    if not isinstance(values, Mapping) or not values:
        raise ValueError("values must be a non-empty mapping of names to literal values")
    items = []
    for name, value in values.items():
        if not isinstance(name, str) or not name:
            raise TypeError(f"value names must be non-empty strings, not {name!r}")
        items.append(f"    {_string(name, 'a value name')}: {literal(value, repr(name))},\n")
    original = "original = {\n" + "".join(items) + "}\n"
    if ast.literal_eval(original.split("=", 1)[1].strip()) != dict(values):  # pragma: no cover - a defect here
        raise AssertionError("the literal does not read back as the values")
    return (
        f"# ORIGINAL VALUES (captured at executedAt = {_captured_at(captured_at)})\n"
        f"{original}"
        "\n"
        f"{_CURRENT_COMMENT}\n"
        f"current = {_recompute(recompute)}\n"
        "\n"
        f"{_DELTAS}"
    )


def comparison_cell(
    notebook: str | os.PathLike[str],
    values: Mapping[str, Any],
    *,
    recompute: str,
    captured_at: str | datetime,
    cell_id: str = COMPARISON_CELL_ID,
) -> str:
    """Append the spec §8.7.4 comparison cell to ``notebook`` as its last cell; return its source.

    ``values`` names the values the execution produced, each a literal (``None``, ``bool``,
    ``int``, finite ``float``, ``str``, or lists and str-keyed dicts of those); anything else is
    refused. ``recompute`` is one line of Python, an expression that returns a mapping with the
    same names, run against live data when the notebook is re-executed (for example
    ``recompute_key_metrics()``). ``captured_at`` is the execution's time, an ISO 8601 string or
    a timezone-aware ``datetime``.

    The cell is a code cell with id ``cell_id`` (nbformat 4.5 or later), no outputs and no
    execution count, and every other byte of the notebook is kept. Append it after executing the
    notebook and before signing it: the cell is part of the signed bytes.
    """
    source = comparison_source(values, recompute=recompute, captured_at=captured_at)
    insert_cell(
        notebook,
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source_lines(source)},
        where="last",
        cell_id=cell_id,
    )
    return source
