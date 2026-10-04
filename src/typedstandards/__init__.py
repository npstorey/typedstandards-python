"""Typed Standards records from Python, through @typedstandards/cli as a child process.

The package vendors @typedstandards/cli and runs it with a located Node binary. It holds no
key, reads no signing seed and computes none of the format's hashes: the CLI reads the seed
from the environment it inherits, and does all of the format's work.
"""

from __future__ import annotations

from ._badge import badge_cell
from ._cli import cli_entry
from ._cli import run as _run
from ._commands import attest, sign, verify, view, withdraw
from ._comparison import comparison_cell
from ._node import NODE_FLOOR, NODE_OVERRIDE, locate_node
from ._show import Shown, show
from ._sidecar import sidecar
from .errors import (
    CliError,
    CliNotVendoredError,
    InternalError,
    NodeLocatorError,
    SeedError,
    UsageError,
    VerificationError,
)
from .pin import Pinned, pin

__version__ = "0.1.0"

#: The version of @typedstandards/cli this release vendors (package.json pins it exactly).
CLI_VERSION = "0.2.0"


def cli_version() -> str:
    """The ``version`` the vendored CLI prints for ``--version``."""
    return _run("--version")["version"]


__all__ = [
    "CLI_VERSION",
    "NODE_FLOOR",
    "NODE_OVERRIDE",
    "CliError",
    "CliNotVendoredError",
    "InternalError",
    "NodeLocatorError",
    "Pinned",
    "SeedError",
    "Shown",
    "UsageError",
    "VerificationError",
    "__version__",
    "attest",
    "badge_cell",
    "cli_entry",
    "cli_version",
    "comparison_cell",
    "locate_node",
    "pin",
    "show",
    "sidecar",
    "sign",
    "verify",
    "view",
    "withdraw",
]
