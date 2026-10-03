"""Locate the Node binary that runs the vendored CLI.

The override variable, when set, names the binary and is the only candidate; otherwise ``node``
on ``PATH``. The candidate's ``node --version`` must be at least the CLI's floor.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from .errors import NodeLocatorError

#: The environment variable that names a Node binary, tried before ``node`` on ``PATH``.
NODE_OVERRIDE = "TYPEDSTANDARDS_NODE"

#: ``engines.node`` of @typedstandards/cli 0.2.0: ``>=20.19``.
NODE_FLOOR = (20, 19, 0)

_VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def _refuse(problem: str) -> NodeLocatorError:
    floor = ".".join(map(str, NODE_FLOOR[:2]))
    return NodeLocatorError(
        f"typedstandards needs Node.js {floor} or later to run @typedstandards/cli: {problem}. "
        f"Install Node {floor} or later, or set {NODE_OVERRIDE} to the path of a Node {floor}+ binary."
    )


def _version_of(binary: str) -> tuple[int, int, int]:
    try:
        proc = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, check=False, timeout=30, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise _refuse(f"{binary} --version could not run ({err})") from err
    printed = proc.stdout.strip()
    match = _VERSION.fullmatch(printed)
    if proc.returncode != 0 or match is None:
        raise _refuse(f"{binary} --version printed {printed!r} (exit {proc.returncode}), not a Node version")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def locate_node() -> str:
    """Return the path of the Node binary to run the CLI with.

    Raises :class:`~typedstandards.errors.NodeLocatorError`, naming the floor and the override
    variable, when no Node is found or the one found is below the floor.
    """
    override = os.environ.get(NODE_OVERRIDE)
    if override:
        binary = shutil.which(override)
        if binary is None:
            raise _refuse(f"{NODE_OVERRIDE} is set to {override!r}, which is not an executable file")
        source = f"{NODE_OVERRIDE} ({binary})"
    else:
        binary = shutil.which("node")
        if binary is None:
            raise _refuse(f"no node on PATH, and {NODE_OVERRIDE} is not set")
        source = f"node on PATH ({binary})"
    version = _version_of(binary)
    if version < NODE_FLOOR:
        raise _refuse(f"{source} is v{'.'.join(map(str, version))}")
    return binary
