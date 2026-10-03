"""Smoke check for an installed typedstandards wheel, run in a fresh environment.

Run it with that environment's Python, outside the source tree's import path, with a test seed in
the environment, as CI's wheel job does:

    TYPEDSTANDARDS_SIGNING_SEED_B64="$(openssl rand -base64 32)" <venv>/bin/python scripts/smoke_wheel.py

It checks the import, CLI_VERSION, the vendored CLI's --version, the vendored tree's licences, and
one sign-then-verify round trip (sign, view, verify) through the vendored CLI. It reads no seed.
"""

from __future__ import annotations

import json
import sys
import sysconfig
from pathlib import Path

import typedstandards


def main() -> int:
    package = Path(typedstandards.__file__).resolve().parent
    site = Path(sysconfig.get_paths()["purelib"]).resolve()
    print(f"typedstandards {typedstandards.__version__} imported from {package}")
    assert package.parent == site, f"imported from {package}, not this environment's site-packages {site}"

    assert typedstandards.CLI_VERSION == "0.2.0", typedstandards.CLI_VERSION
    printed = typedstandards.cli_version()
    print(f"CLI_VERSION {typedstandards.CLI_VERSION}; the vendored CLI's --version prints {printed}")
    assert printed == typedstandards.CLI_VERSION

    entry = typedstandards.cli_entry()
    assert entry.is_relative_to(package / "_vendor"), entry
    vendor = package / "_vendor"
    lock = json.loads((vendor / "package-lock.json").read_text(encoding="utf-8"))
    vendored = [key for key in lock["packages"] if key]
    for key in vendored:
        assert (vendor / key / "LICENSE").is_file(), f"{key} has no licence file in the wheel"
    assert not (vendor / "node_modules" / ".bin").exists()
    print(f"{len(vendored)} vendored packages, each with its licence file")
    print(f"node: {typedstandards.locate_node()}")

    record = {
        "type": "content/analysis/v1",
        "producerProfile": "scripted-recomputation/typedstandards-python-smoke",
        "captureMethod": "script-run",
        "prompt": "Smoke-check the installed wheel.",
        "promptVisibility": "full_text",
        "queries": [],
        "dataSources": [],
        "cost": {"model": "none"},
        "skillMetadata": {},
        "trace": {},
        "output": "The wheel signs and verifies.",
        "signer": {"bindingTier": "pseudonymous", "displayName": "typedstandards-python smoke check"},
    }
    signed = typedstandards.sign(record)
    bundle = typedstandards.view(signed, visibility="public", title="Smoke check")
    result = typedstandards.verify(bundle)
    print(f"signed {signed['envelopeHash']}; verify ok={result['ok']} status={result['lifecycle']['status']}")
    assert result["ok"] is True
    assert result["nodeId"] == signed["envelopeHash"]
    print("smoke check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
