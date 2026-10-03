"""Run the vendored CLI as a child process and read its result."""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ._node import locate_node
from .errors import (
    CliError,
    CliNotVendoredError,
    InternalError,
    SeedError,
    UsageError,
    VerificationError,
)

#: The CLI's entry file inside the vendored tree that hatch_build.py writes.
CLI_ENTRY = Path(__file__).parent / "_vendor" / "node_modules" / "@typedstandards" / "cli" / "dist" / "bin" / "main.js"

#: The CLI's exit codes (packages/cli/src/errors.ts:3-14 in typedstandards). 1 is handled apart,
#: since verify prints its verdict before exiting 1.
_RAISES: dict[int, type[CliError]] = {2: UsageError, 3: SeedError, 4: InternalError}

_log = logging.getLogger("typedstandards")


def cli_entry() -> Path:
    """The vendored CLI's entry file; raises :class:`CliNotVendoredError` when it is missing."""
    if not CLI_ENTRY.is_file():
        raise CliNotVendoredError(
            f"the vendored @typedstandards/cli is missing ({CLI_ENTRY}); reinstall typedstandards, or in a "
            "checkout run `uv sync --reinstall-package typedstandards`"
        )
    return CLI_ENTRY


def _parse(stdout: bytes) -> Any:
    return json.loads(stdout.decode("utf-8"))


def run(command: str, args: Sequence[str] = (), *, stdin: bytes | None = None) -> Any:
    """Run one CLI command and return its stdout parsed as JSON.

    The child inherits this process's environment: no ``env`` is passed, and nothing here reads
    or sets a variable for it. What the CLI writes on stderr when it succeeds (attention
    readings, such as an offline ``registry_unavailable``) is logged at INFO on the
    ``typedstandards`` logger.
    """
    node = locate_node()
    entry = cli_entry()
    feed: dict[str, Any] = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    proc = subprocess.run([node, str(entry), command, *args], capture_output=True, check=False, **feed)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    code = proc.returncode
    if code == 0:
        for line in stderr.splitlines():
            _log.info("%s", line)
        try:
            return _parse(proc.stdout)
        except ValueError as err:
            raise CliError(0, f"stdout is not JSON ({err}); stderr: {stderr}", command) from err
    if code == 1:
        # verify prints {ok: false, ...} before exiting 1; sign, withdraw and attest print nothing.
        try:
            document = _parse(proc.stdout) if proc.stdout.strip() else None
        except ValueError:
            document = None
        raise VerificationError(code, stderr, command, document)
    raise _RAISES.get(code, CliError)(code, stderr, command)
