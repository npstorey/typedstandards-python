"""Acceptance 3: ``comparison_cell``.

It appends the spec §8.7.4 comparison cell as the notebook's last code cell, with the caller's
values as literals, the recompute line and the delta lines; the notebook stays valid JSON that
the real CLI signs inline; a value that is not a literal is refused.
"""

from __future__ import annotations

import ast
import contextlib
import enum
import io
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import nbformat
import pytest
from support import analysis_input, synthetic_notebook

import typedstandards
from typedstandards import comparison_cell

VALUES = {
    "rows": 1204,
    "mean_fare": 13.75,
    "share_late": 0.0825,
    "district": "Café “north”",
    "complete": True,
    "note": None,
    "by_month": [101, 99.5, None],
    "split": {"weekday": 812, "weekend": 392},
}
RECOMPUTE = "recompute_key_metrics()"
CAPTURED_AT = "2026-10-03T12:00:00Z"

EXPECTED_SOURCE = (
    "# ORIGINAL VALUES (captured at executedAt = 2026-10-03T12:00:00Z)\n"
    "original = {\n"
    '    "rows": 1204,\n'
    '    "mean_fare": 13.75,\n'
    '    "share_late": 0.0825,\n'
    '    "district": "Café “north”",\n'
    '    "complete": True,\n'
    '    "note": None,\n'
    '    "by_month": [101, 99.5, None],\n'
    '    "split": {"weekday": 812, "weekend": 392},\n'
    "}\n"
    "\n"
    "# CURRENT VALUES (re-computed against live data using the same helpers + queries above)\n"
    "current = recompute_key_metrics()\n"
    "\n"
    "# DELTAS\n"
    "for k in original:\n"
    "    delta = (current[k] - original[k]) if isinstance(original[k], (int, float)) else (original[k], current[k])\n"
    '    print(f"{k}: original={original[k]}, current={current[k]}, delta={delta}")\n'
)


def _notebook(tmp_path: Path, **style: Any) -> tuple[Path, str]:
    text = synthetic_notebook(**style)
    path = tmp_path / "analysis.ipynb"
    path.write_bytes(text.encode("utf-8"))
    return path, text


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def test_appends_the_spec_shaped_cell_last(tmp_path: Path) -> None:
    path, original = _notebook(tmp_path)
    source = comparison_cell(path, VALUES, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    assert source == EXPECTED_SOURCE

    written = _read(path)
    notebook = json.loads(written)  # still valid JSON
    before = json.loads(original)
    assert notebook["cells"][:-1] == before["cells"]
    cell = notebook["cells"][-1]
    assert cell == {
        "cell_type": "code",
        "execution_count": None,
        "id": "typedstandards-comparison",
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }
    # Every byte before the new cell is the author's, and so is the file's tail.
    last_end = original.rindex("}", 0, original.index('"metadata": {\n  "kernelspec"')) + 1
    assert written.startswith(original[:last_end])
    assert written.endswith(original[last_end:])
    nbformat.validate(nbformat.reads(written, as_version=nbformat.NO_CONVERT))


def test_the_values_are_literals_that_read_back(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path)
    source = comparison_cell(path, VALUES, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    tree = ast.parse(source)
    original = next(n for n in tree.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "original")
    assert ast.literal_eval(original.value) == VALUES
    current = next(n for n in tree.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "current")
    assert ast.unparse(current.value) == RECOMPUTE


def test_the_cell_runs_and_prints_the_deltas(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path)
    values = {"rows": 1204, "mean_fare": 13.75, "district": "north"}
    source = comparison_cell(path, values, recompute="recompute()", captured_at=CAPTURED_AT)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(source, {"recompute": lambda: {"rows": 1210, "mean_fare": 14.0, "district": "south"}})  # noqa: S102
    assert out.getvalue().splitlines() == [
        "rows: original=1204, current=1210, delta=6",
        "mean_fare: original=13.75, current=14.0, delta=0.25",
        "district: original=north, current=south, delta=('north', 'south')",
    ]


def test_the_real_cli_signs_the_notebook_inline(tmp_path: Path, seed: str) -> None:
    """With a throwaway seed (the ``seed`` fixture), through the wrapper, exit 0."""
    path, _ = _notebook(tmp_path)
    typedstandards.badge_cell(
        "https://records.example.org/bundles/analysis.bundle.json", capture_method="script-run", notebook=path
    )
    comparison_cell(path, VALUES, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    signed = typedstandards.sign(analysis_input(), output_file=path)  # raises on any non-zero exit
    assert signed["package"]["output"] == _read(path)
    assert signed["package"]["contentCanonicalization"].endswith("/raw-bytes/v1")
    assert typedstandards.verify(signed)["ok"] is True


def test_captured_at_from_a_datetime(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path)
    when = datetime(2026, 10, 3, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    source = comparison_cell(path, {"rows": 1}, recompute=RECOMPUTE, captured_at=when)
    assert source.startswith("# ORIGINAL VALUES (captured at executedAt = 2026-10-03T12:00:00.000Z)\n")


class Status(enum.IntEnum):
    OK = 3


class Fare(float):
    def __repr__(self) -> str:
        return "Fare(...)"


def test_int_and_float_subclasses_are_written_as_their_value(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path)
    source = comparison_cell(
        path, {"status": Status.OK, "fare": Fare(2.5)}, recompute=RECOMPUTE, captured_at=CAPTURED_AT
    )
    assert '    "status": 3,\n    "fare": 2.5,\n' in source


class Thing:
    pass


NOT_LITERALS = {
    "object": Thing(),
    "function": lambda: 1,
    "builtin": len,
    "tuple": (1, 2),
    "set": {1, 2},
    "bytes": b"x",
    "complex": 1j,
    "datetime": datetime(2026, 10, 3, tzinfo=UTC),
    "nested object": {"a": [1, Thing()]},
    "non-str key": {1: "a"},
}


@pytest.mark.parametrize("value", NOT_LITERALS.values(), ids=NOT_LITERALS.keys())
def test_a_value_that_is_not_a_literal_is_refused(tmp_path: Path, value: Any) -> None:
    path, original = _notebook(tmp_path)
    with pytest.raises(TypeError, match="not a literal|not a string"):
        comparison_cell(path, {"rows": 1, "bad": value}, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    assert _read(path) == original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_a_non_finite_float_is_refused(tmp_path: Path, value: float) -> None:
    path, original = _notebook(tmp_path)
    with pytest.raises(ValueError, match="no Python literal"):
        comparison_cell(path, {"bad": value}, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    assert _read(path) == original


@pytest.mark.parametrize("recompute", ["", "x = recompute()", "a()\nb()", "import os", "recompute("])
def test_a_recompute_that_is_not_one_expression_is_refused(tmp_path: Path, recompute: str) -> None:
    path, _ = _notebook(tmp_path)
    with pytest.raises(ValueError, match="recompute"):
        comparison_cell(path, {"rows": 1}, recompute=recompute, captured_at=CAPTURED_AT)


@pytest.mark.parametrize("when", ["yesterday", "2026-10-03T12:00:00Z\nprint(1)", datetime(2026, 10, 3)])
def test_a_bad_capture_time_is_refused(tmp_path: Path, when: Any) -> None:
    path, _ = _notebook(tmp_path)
    with pytest.raises(ValueError, match="captured_at"):
        comparison_cell(path, {"rows": 1}, recompute=RECOMPUTE, captured_at=when)


def test_no_values_is_refused(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        comparison_cell(path, {}, recompute=RECOMPUTE, captured_at=CAPTURED_AT)


def test_a_second_comparison_cell_is_refused(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path)
    comparison_cell(path, {"rows": 1}, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    with pytest.raises(ValueError, match="already has a cell with id 'typedstandards-comparison'"):
        comparison_cell(path, {"rows": 1}, recompute=RECOMPUTE, captured_at=CAPTURED_AT)


def test_ascii_escaped_notebook_stays_ascii(tmp_path: Path) -> None:
    path, _ = _notebook(tmp_path, ensure_ascii=True)
    comparison_cell(path, VALUES, recompute=RECOMPUTE, captured_at=CAPTURED_AT)
    written = path.read_bytes()
    assert written.isascii()
    assert "".join(json.loads(written)["cells"][-1]["source"]) == EXPECTED_SOURCE
