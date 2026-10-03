"""Run the vendored CLI as a child process and read its result."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ._node import locate_node
from .errors import CliError, CliNotVendoredError

#: The CLI's entry file inside the vendored tree that hatch_build.py writes.
CLI_ENTRY = Path(__file__).parent / "_vendor" / "node_modules" / "@typedstandards" / "cli" / "dist" / "bin" / "main.js"


def cli_entry() -> Path:
    """The vendored CLI's entry file; raises :class:`CliNotVendoredError` when it is missing."""
    if not CLI_ENTRY.is_file():
        raise CliNotVendoredError(
            f"the vendored @typedstandards/cli is missing ({CLI_ENTRY}); reinstall typedstandards, or in a "
            "checkout run `uv sync --reinstall-package typedstandards`"
        )
    return CLI_ENTRY


def run(command: str, args: Sequence[str] = (), *, stdin: bytes | None = None) -> Any:
    """Run one CLI command and return its stdout parsed as JSON.

    The child inherits this process's environment: no ``env`` is passed, and nothing here
    reads or sets a variable for it.
    """
    node = locate_node()
    entry = cli_entry()
    feed: dict[str, Any] = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    proc = subprocess.run([node, str(entry), command, *args], capture_output=True, check=False, **feed)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode == 0:
        if stderr:
            sys.stderr.write(stderr)
        try:
            return json.loads(proc.stdout.decode("utf-8"))
        except ValueError as err:
            raise CliError(0, f"stdout is not JSON ({err}); stderr: {stderr}", command) from err
    raise CliError(proc.returncode, stderr, command)
