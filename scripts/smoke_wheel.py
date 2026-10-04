"""Smoke check for an installed typedstandards wheel, run in a fresh environment.

Run it with that environment's Python, outside the source tree's import path, with a test seed in
the environment, as CI's wheel job does:

    TYPEDSTANDARDS_SIGNING_SEED_B64="$(openssl rand -base64 32)" <venv>/bin/python scripts/smoke_wheel.py

It checks the import, CLI_VERSION, the vendored CLI's --version, the vendored tree's licences,
one sign-then-verify round trip (sign, view, verify) through the vendored CLI, and the five
helpers with the runtime dependencies the wheel declares (httpx for pin, PyYAML for sidecar),
offline: pin over httpx.MockTransport. It reads no seed.
"""

from __future__ import annotations

import json
import sys
import sysconfig
import tempfile
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

    entry = typedstandards.cli_entry().resolve()
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
    helpers(record)
    print("smoke check passed")
    return 0


def helpers(record: dict) -> None:
    import httpx

    def portal(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/views/abcd-1234":
            return httpx.Response(200, json={"rowsUpdatedAt": 1790991539})
        return httpx.Response(200, content=b"a,b\n1,2\n")

    content, entry = typedstandards.pin(
        "https://data.example.org/resource/abcd-1234.csv", transport=httpx.MockTransport(portal)
    )
    assert content == b"a,b\n1,2\n" and entry["arguments"]["rowsUpdatedAt"] == 1790991539, entry

    with tempfile.TemporaryDirectory() as tmp:
        notebook = Path(tmp) / "analysis.ipynb"
        cells = [{"cell_type": "code", "execution_count": None, "id": "a", "metadata": {}, "outputs": [], "source": []}]
        document = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        notebook.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        typedstandards.badge_cell(
            "https://records.example.org/bundles/analysis.bundle.json", capture_method="script-run", notebook=notebook
        )
        typedstandards.comparison_cell(
            notebook, {"rows": 2}, recompute="recompute()", captured_at="2026-10-03T00:00:00Z"
        )
        inline = {k: v for k, v in record.items() if k != "output"}
        signed = typedstandards.sign({**inline, "queries": [entry]}, output_file=notebook)
        bundle = typedstandards.view(signed, visibility="public")
        result = typedstandards.verify(bundle)
        assert result["ok"] is True
        yaml_path = typedstandards.sidecar(bundle, notebook)
        assert yaml_path.name == "analysis.ipynb.record.yaml", yaml_path
        html = typedstandards.show(bundle, result)._repr_html_()
        assert "Signed with a self-certifying key" in html
    print("helpers: pin, badge_cell, comparison_cell, sidecar and show ran from the installed wheel")


if __name__ == "__main__":
    sys.exit(main())
