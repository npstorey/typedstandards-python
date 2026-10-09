"""Live smoke check of ``publish``: sign one record and publish it to a host made from the host
template's publish mode (typedstandards#141, gate G3). It writes one commit to that repository.

Run by the owner, with the installed wheel's Python, outside the source tree's import path, from a
terminal signed in to the secret store (``op signin``):

    op run --env-file=publish-check.env -- <venv>/bin/python scripts/smoke_publish.py

where ``publish-check.env`` maps ``TYPEDSTANDARDS_GITHUB_TOKEN`` (a fine-grained token for that
repository alone, Contents read and write) and the CLI's signing-seed variable to secret
references. The script reads neither: ``publish`` reads the token's variable, and the CLI, run by
``sign``, reads the seed from the environment it inherits.

It prints only the receipt's fields, none of which is secret, and exits non-zero on any refusal
or error: 2 a refusal before any write, 3 an API error, 4 a CLI error, 5 a receipt whose URLs are
not under ``--origin``. ``--repository``, ``--branch`` and ``--origin`` default to the scratch
copy the sprint's live checks use.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typedstandards as ts

REPOSITORY = "npstorey/typedstandards-publish-check"
ORIGIN = "https://publish-check.typedstandards.org"


def notebook_text(when: str) -> str:
    cells = [
        {
            "cell_type": "markdown",
            "id": "check",
            "metadata": {},
            "source": [f"# Publish check\n\nA record signed and published by `scripts/smoke_publish.py` at {when}.\n"],
        }
    ]
    document = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def record() -> dict[str, Any]:
    return {
        "type": "content/analysis/v1",
        "producerProfile": "scripted-recomputation/typedstandards-python-publish-check",
        "captureMethod": "script-run",
        "prompt": "Sign and publish one record from the installed wheel.",
        "promptVisibility": "full_text",
        "queries": [],
        "dataSources": [],
        "cost": {"model": "none"},
        "skillMetadata": {},
        "trace": {},
        "signer": {"bindingTier": "pseudonymous", "displayName": "typedstandards-python publish check"},
    }


def main(argv: list[str] | None = None, *, transport: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--origin", default=ORIGIN)
    args = parser.parse_args(argv)
    when = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    print(f"typedstandards {ts.__version__}; publishing one record to {args.repository} ({args.branch})")
    try:
        with tempfile.TemporaryDirectory() as directory:
            notebook = Path(directory) / "publish-check.ipynb"
            notebook.write_text(notebook_text(when), encoding="utf-8")
            signed = ts.sign(record(), output_file=notebook)
            print(f"signed {signed['envelopeHash']} by {signed['package']['signer']['identifier']}")
            host = ts.GitHubPagesHost(args.repository, branch=args.branch, transport=transport)
            receipt = ts.publish(signed, host=host, notebook=notebook, title=f"Publish check, {when}")
    except ts.PublishRefusedError as error:
        print(f"refused, nothing written: {error}")
        return 2
    except ts.PublishError as error:
        print(f"error: {error}")
        return 3
    except ts.CliError as error:
        print(f"the CLI exited {error.exit_code}: {error}")
        return 4
    for key in ("name", "written", "commit", "bundle_url", "verify_url", "registry_url", "run"):
        print(f"{key}: {receipt[key]}")
    if not receipt["bundle_url"].startswith(f"{args.origin}/bundles/"):
        print(f"the receipt's bundle_url is not under {args.origin}: host.json's origin differs")
        return 5
    print("publish check passed: the host's workflow now builds and deploys the commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
