"""Shared test helpers (no tests of their own).

Tests set the signing seed in ``os.environ`` (``monkeypatch.setenv``), and the wrapper's child
process inherits it. Test code may generate a random seed; package code never touches one.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import stat
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_PATH = FIXTURES / "reference-golden.json"
BUNDLE_PATH = FIXTURES / "first-note.bundle.json"

# The CLI's variable (packages/cli/src/seed.ts:9 in typedstandards). Named here, in tests only.
SEED_VARIABLE = "TYPEDSTANDARDS_SIGNING_SEED_B64"

# RFC 8032 §7.1 TEST 1, the published test vector's 32-byte seed, as hex (the CLI's
# harness.test.ts:36). Its base64 is derived at run time.
RFC8032_TEST_1 = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"


def rfc8032_test_1_b64() -> str:
    return base64.b64encode(bytes.fromhex(RFC8032_TEST_1)).decode("ascii")


def fresh_seed_b64() -> str:
    """A fresh random seed for one test. Never a real key."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def envelope_case(name: str) -> dict[str, Any]:
    return next(c for c in load_golden()["envelopeCases"] if c["name"] == name)


def self_certifying_input() -> dict[str, Any]:
    """The golden's v01-default input, without its fixed packageId, createdAt and signingKeyId,
    and with a self-certifying signer, whose identifier the CLI fills with the seed's did:key."""
    value = copy.deepcopy(envelope_case("v01-default")["input"])
    for key in ("packageId", "createdAt", "signingKeyId"):
        value.pop(key, None)
    value["signer"] = {"bindingTier": "pseudonymous", "displayName": "Example signer"}
    return value


def write_stub(directory: Path, name: str, version: str, exit_code: int = 4, stderr: str = "") -> Path:
    """A stand-in Node binary: prints ``version`` for ``--version``; otherwise writes ``stderr``
    and exits ``exit_code``."""
    path = directory / name
    path.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo {version}; exit 0; fi\n'
        f"printf '%s\\n' '{stderr}' >&2\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class NetworkBlocked(RuntimeError):
    """Raised by conftest.py's autouse guard when a test opens a connection or binds a port."""


def synthetic_notebook(
    *,
    minor: int = 5,
    indent: int | None = 1,
    ensure_ascii: bool = False,
    newline: str = "\n",
    cells: list[dict[str, Any]] | None = None,
) -> str:
    """A small notebook's text, written as nbformat writes it by default (sorted keys, indent 1,
    a trailing newline, raw UTF-8), or in another style for the splice tests."""
    if cells is None:
        cells = [
            {
                "cell_type": "markdown",
                "id": "intro",
                "metadata": {},
                "source": ["# Example analysis\n", "\n", "Résumé of the method — café 実験.\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "id": "load",
                "metadata": {"tags": ["parameters"]},
                "outputs": [{"name": "stdout", "output_type": "stream", "text": ["1.50\n"]}],
                "source": ["total = 1.50\n", "print(f'{total:.2f}')"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "plot",
                "metadata": {},
                "outputs": [],
                "source": ["values = [1e-3, 2.0, -0.0]"],
            },
        ]
        if minor < 5:
            for cell in cells:
                del cell["id"]
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12.0"},
        },
        "nbformat": 4,
        "nbformat_minor": minor,
    }
    if indent is None:
        return json.dumps(notebook, sort_keys=True, ensure_ascii=ensure_ascii)
    text = json.dumps(notebook, sort_keys=True, indent=indent, ensure_ascii=ensure_ascii, separators=(",", ": "))
    return (text + "\n").replace("\n", newline)


def analysis_input(**extra: Any) -> dict[str, Any]:
    """A scripted-recomputation envelope input for a file signed inline (``output_file``), with a
    self-certifying signer whose identifier the CLI fills with the seed's did:key."""
    value: dict[str, Any] = {
        "type": "content/analysis/v1",
        "producerProfile": "scripted-recomputation/example",
        "captureMethod": "script-run",
        "prompt": "Run the example notebook end to end and record its output.",
        "promptVisibility": "full_text",
        "queries": [
            {"tool": "jupyter nbconvert --execute", "operationType": "script-run", "arguments": {"notebook": "x"}}
        ],
        "dataSources": [],
        "cost": {"model": "none"},
        "skillMetadata": {},
        "trace": {"resourceSpans": []},
        "signer": {"bindingTier": "pseudonymous", "displayName": "Example analyst"},
    }
    value.update(extra)
    return value
