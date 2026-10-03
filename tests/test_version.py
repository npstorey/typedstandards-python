"""Acceptance 5, first half: CLI_VERSION is the version of the CLI the wrapper runs.

The vendored CLI's ``--version`` prints JSON (packages/cli/src/run.ts:61-63 in typedstandards),
not a bare string; its ``version`` must equal CLI_VERSION, as must the vendored package.json and
the pin in this repository's package.json and package-lock.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import typedstandards
from typedstandards._cli import run

ROOT = Path(__file__).parent.parent


def test_cli_version_is_the_pin() -> None:
    assert typedstandards.CLI_VERSION == "0.2.0"


def test_vendored_cli_prints_cli_version() -> None:
    printed = run("--version")
    assert printed == {"name": "@typedstandards/cli", "version": typedstandards.CLI_VERSION}
    assert typedstandards.cli_version() == typedstandards.CLI_VERSION


def test_vendored_package_json_is_cli_version() -> None:
    manifest = typedstandards.cli_entry().parents[2] / "package.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["name"] == "@typedstandards/cli"
    assert data["version"] == typedstandards.CLI_VERSION


def test_repository_pin_is_cli_version() -> None:
    """The committed package.json pins the CLI exactly, and the lock resolves that version."""
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert package["dependencies"] == {"@typedstandards/cli": typedstandards.CLI_VERSION}
    assert lock["packages"]["node_modules/@typedstandards/cli"]["version"] == typedstandards.CLI_VERSION
