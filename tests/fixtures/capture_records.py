"""Capture the record fixtures that ``show`` and ``sidecar`` are tested against.

Run once, from the repository root, with a throwaway seed that is never stored:

    TYPEDSTANDARDS_SIGNING_SEED_B64="$(openssl rand -base64 32)" uv run python tests/fixtures/capture_records.py

It signs two records through the wrapper (so through the vendored CLI): an active analysis
notebook and a claim that is then withdrawn, each with a ``vcsRef`` and a role under
``extensions``. For each it writes what ``sign`` printed, the bundle ``view`` printed, and what
``verify --json`` printed for that bundle; for the claim, also what ``withdraw`` printed. The
seed is read by the CLI from the environment this script inherits; the script never reads it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from support import analysis_input, synthetic_notebook  # noqa: E402

import typedstandards  # noqa: E402

VCS = {
    "repoUrl": "https://git.example.com/example/analysis",
    "commitSha": "0123456789abcdef0123456789abcdef01234567",
    "ref": "refs/heads/main",
}


def write(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        notebook = Path(tmp) / "analysis.ipynb"
        notebook.write_text(synthetic_notebook(), encoding="utf-8")
        typedstandards.badge_cell(
            "https://records.example.org/bundles/analysis.bundle.json", capture_method="script-run", notebook=notebook
        )
        typedstandards.comparison_cell(
            notebook, {"total": 1.5}, recompute="recompute_key_metrics()", captured_at="2026-10-03T12:00:00Z"
        )
        active = typedstandards.sign(
            analysis_input(
                packageId="6f9e2a54-6d1c-4f1e-9a52-3c7d1f0b8e21",
                createdAt="2026-10-03T12:05:00.000Z",
                summary="An example analysis notebook, executed end to end.",
                extensions={"role": "analysis"},
                vcsRef={**VCS, "path": "notebooks/analysis.ipynb"},
            ),
            output_file=notebook,
        )

        claim = Path(tmp) / "claim.md"
        claim.write_text("The median fare rose by 4 percent between the two periods.\n", encoding="utf-8")
        withdrawn = typedstandards.sign(
            analysis_input(
                packageId="0b3c8d7e-2f41-4a9b-8c65-91d2e4f7a3b0",
                createdAt="2026-10-03T12:06:00.000Z",
                summary="An example claim drawn from the analysis notebook.",
                extensions={"role": "claim"},
                vcsRef={**VCS, "path": "claims/median-fare.md"},
            ),
            output_file=claim,
        )

    withdrawal = typedstandards.withdraw(
        {
            "targetNodeId": withdrawn["envelopeHash"],
            "reason": "The claim compared periods of different lengths; a restatement replaces it.",
            "signer": withdrawn["package"]["signer"],
            "packageId": "5a1d9c3e-7b20-4e8f-a6d4-2c9b0e1f3a57",
            "createdAt": "2026-10-03T12:30:00.000Z",
            "effectiveAt": "2026-10-03T12:30:00.000Z",
        }
    )

    active_bundle = typedstandards.view(active, visibility="public", title="Example analysis")
    withdrawn_bundle = typedstandards.view(
        withdrawn, visibility="public", attestations=[withdrawal], title="Example claim"
    )

    write("record-active.signed.json", active)
    write("record-active.bundle.json", active_bundle)
    write("record-active.verify.json", typedstandards.verify(active_bundle))
    write("record-withdrawn.signed.json", withdrawn)
    write("record-withdrawn.withdrawal.json", withdrawal)
    write("record-withdrawn.bundle.json", withdrawn_bundle)
    write("record-withdrawn.verify.json", typedstandards.verify(withdrawn_bundle))
    print(f"captured with @typedstandards/cli {typedstandards.cli_version()}")


if __name__ == "__main__":
    main()
