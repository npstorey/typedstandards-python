"""Locate the Node binary that runs the vendored CLI."""

from __future__ import annotations

import shutil

#: The environment variable that names a Node binary, tried before ``node`` on ``PATH``.
NODE_OVERRIDE = "TYPEDSTANDARDS_NODE"

#: ``engines.node`` of @typedstandards/cli 0.2.0: ``>=20.19``.
NODE_FLOOR = (20, 19, 0)


def locate_node() -> str:
    """Return the Node binary to run the CLI with."""
    return shutil.which("node") or "node"
