"""``sidecar``: the commitment view as a sibling YAML file (spec §8.8.3).

Spec §8.8.3 names the file ``<artifact-basename>.record.yaml`` and fills it with the §8.8.1
field set at the top level. ``view`` prints the §8.8.1 view plus the inline ``package``, and a
bundle served by ``@typedstandards/host-core`` also carries ``trustRegistry``. Neither of those
two is a §8.8.1 field (§8.8.1 calls them the two fields the self-contained serialization
inlines), so the sidecar leaves both out and carries every other field ``view`` printed, in the
order it printed them.

**The basename.** The spec does not say whether ``<artifact-basename>`` keeps the artifact's
extension. The sidecar keeps it: ``analysis.ipynb`` gets ``analysis.ipynb.record.yaml``. That is
the POSIX ``basename`` of the artifact's path; it cannot collide when two artifacts share a stem
(a notebook ``analysis.ipynb`` beside a dashboard source ``analysis.py``); and the artifact's
name is the sidecar's name minus ``.record.yaml``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Spec §8.8.1's fields, in its table's order (``evidenceProtocolVersion`` is the dual-era key).
COMMITMENT_VIEW_FIELDS = (
    "protocolVersion",
    "evidenceProtocolVersion",
    "packageHash",
    "packageUrl",
    "visibility",
    "captureMethod",
    "contentProfile",
    "producerProfile",
    "type",
    "signer",
    "contentHash",
    "contentCanonicalization",
    "signature",
    "signerIdentity",
    "rfc3161Timestamp",
    "rekorEntryId",
    "rekorInclusionProof",
    "rekorEntryBody",
    "lifecycle",
    "lifecycleAttestations",
    "attestations",
    "trustRegistryUrl",
    "trustRegistryUrlLegacy",
    "subjectTitle",
    "subjectSummary",
)

#: What ``view`` and a served bundle inline beyond §8.8.1; the sidecar leaves these out.
INLINED = ("package", "trustRegistry")

SUFFIX = ".record.yaml"


def sidecar_name(artifact: str | os.PathLike[str]) -> str:
    """``<artifact's file name>.record.yaml``: ``analysis.ipynb`` gives ``analysis.ipynb.record.yaml``."""
    name = Path(artifact).name
    if not name:
        raise ValueError(f"{os.fspath(artifact)!r} names no file")
    return name + SUFFIX


def commitment_fields(view: Mapping[str, Any]) -> dict[str, Any]:
    """``view`` without ``package`` and ``trustRegistry``, in the order ``view`` printed it."""
    if not isinstance(view, Mapping) or "packageHash" not in view:
        raise ValueError("sidecar takes what view printed (a commitment view, with packageHash)")
    return {key: value for key, value in view.items() if key not in INLINED}


def sidecar(
    view: Mapping[str, Any] | str | os.PathLike[str],
    artifact: str | os.PathLike[str],
    *,
    directory: str | os.PathLike[str] | None = None,
) -> Path:
    """Write ``<artifact's file name>.record.yaml`` from what :func:`~typedstandards.view` printed.

    ``view`` is the view (or a bundle a host serves), as a mapping or the path of its JSON.
    ``artifact`` is the signed file; only its name is used, and the sidecar is written beside it
    unless ``directory`` names another place. Returns the sidecar's path.

    The file holds every field of the view except ``package`` and ``trustRegistry``, in the
    view's order, as YAML (``yaml.safe_dump``, Unicode kept). Every value loads back as the JSON
    value it came from: a string such as ``"0.1.0"`` or a timestamp stays a string.
    """
    import yaml

    if not isinstance(view, Mapping):
        view = json.loads(Path(view).read_bytes())
    fields = commitment_fields(view)  # type: ignore[arg-type]
    text = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1 << 20)
    if yaml.safe_load(text) != fields:  # pragma: no cover - a defect in the dump, never the input
        raise AssertionError("the YAML does not load back as the view's fields")
    target = Path(directory) if directory is not None else Path(artifact).parent
    path = target / sidecar_name(artifact)
    path.write_text(text, encoding="utf-8")
    return path
