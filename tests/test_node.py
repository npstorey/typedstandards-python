"""Acceptance 3: the Node locator.

The floor is 20.19.0, @typedstandards/cli 0.2.0's engines.node. TYPEDSTANDARDS_NODE names a Node
binary and is tried first; then ``node`` on PATH. With no Node, or one below the floor, the
wrapper raises NodeLocatorError naming 20.19 and the override before the CLI runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from support import self_certifying_input, write_stub

import typedstandards
from typedstandards import NODE_OVERRIDE, NodeLocatorError


def _names_floor_and_override(err: NodeLocatorError) -> None:
    message = str(err)
    assert "20.19" in message
    assert NODE_OVERRIDE in message


def test_override_variable_is_named() -> None:
    assert NODE_OVERRIDE == "TYPEDSTANDARDS_NODE"
    assert typedstandards.NODE_FLOOR == (20, 19, 0)


def test_no_node_on_path_and_no_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NODE_OVERRIDE, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(NodeLocatorError) as caught:
        typedstandards.sign(self_certifying_input())
    _names_floor_and_override(caught.value)


def test_node_below_the_floor_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_stub(tmp_path, "node", "v20.18.0")
    monkeypatch.delenv(NODE_OVERRIDE, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(NodeLocatorError) as caught:
        typedstandards.sign(self_certifying_input())
    _names_floor_and_override(caught.value)
    assert "20.18.0" in str(caught.value)


def test_node_below_the_floor_by_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The override is tried before PATH, so an old override fails even with a good node on PATH."""
    stub = write_stub(tmp_path, "old-node", "v20.18.0")
    monkeypatch.setenv(NODE_OVERRIDE, str(stub))
    with pytest.raises(NodeLocatorError) as caught:
        typedstandards.sign(self_certifying_input())
    _names_floor_and_override(caught.value)


def test_node_at_the_floor_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = write_stub(tmp_path, "node", "v20.19.0")
    monkeypatch.delenv(NODE_OVERRIDE, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert typedstandards.locate_node() == str(stub)


def test_override_comes_before_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = write_stub(tmp_path, "pinned-node", "v24.0.0")
    monkeypatch.setenv(NODE_OVERRIDE, str(stub))
    assert shutil.which("node") != str(stub)
    assert typedstandards.locate_node() == str(stub)


def test_override_that_is_not_a_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NODE_OVERRIDE, str(tmp_path / "missing-node"))
    with pytest.raises(NodeLocatorError) as caught:
        typedstandards.locate_node()
    _names_floor_and_override(caught.value)
    assert "missing-node" in str(caught.value)


@pytest.mark.parametrize("printed", ["", "node", "20.19.0", "v20"])
def test_unreadable_version(printed: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = write_stub(tmp_path, "odd-node", printed or "''")
    monkeypatch.setenv(NODE_OVERRIDE, str(stub))
    with pytest.raises(NodeLocatorError) as caught:
        typedstandards.locate_node()
    _names_floor_and_override(caught.value)


@pytest.mark.parametrize(
    ("printed", "ok"),
    [
        ("v20.18.9", False),
        ("v19.99.0", False),
        ("v20.19.0", True),
        ("v20.20.1", True),
        ("v22.0.0", True),
        ("v100.0.0", True),
    ],
)
def test_floor_comparison(printed: str, ok: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = write_stub(tmp_path, "node-under-test", printed)
    monkeypatch.setenv(NODE_OVERRIDE, str(stub))
    if ok:
        assert typedstandards.locate_node() == str(stub)
    else:
        with pytest.raises(NodeLocatorError):
            typedstandards.locate_node()


def test_the_test_runners_node_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NODE_OVERRIDE, raising=False)
    assert typedstandards.locate_node() == shutil.which("node")
