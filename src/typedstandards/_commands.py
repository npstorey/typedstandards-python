"""The five pass-through commands: ``sign``, ``withdraw``, ``attest``, ``view``, ``verify``.

Each takes the CLI's inputs as Python values and returns the CLI's stdout parsed as JSON.
An input given as a mapping is sent as JSON on standard input (``--input -``); a ``str`` or
``os.PathLike`` is a path the CLI reads. The wrapper computes nothing the format defines: the
CLI builds, signs, hashes and verifies.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ._cli import run

#: An input: a JSON object as a mapping, or the path of a JSON file.
Input = Mapping[str, Any] | str | os.PathLike[str]


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _input_args(value: Input, flag: str) -> tuple[list[str], bytes | None]:
    if isinstance(value, Mapping):
        return [flag, "-"], _json_bytes(value)
    if isinstance(value, (str, os.PathLike)):
        return [flag, os.fspath(value)], None
    raise TypeError(f"{flag} takes a mapping (sent as JSON on stdin) or a path, not {type(value).__name__}")


def _as_file(value: Input, directory: str, name: str, what: str) -> str:
    if isinstance(value, Mapping):
        path = Path(directory) / name
        path.write_bytes(_json_bytes(value))
        return str(path)
    if isinstance(value, (str, os.PathLike)):
        return os.fspath(value)
    raise TypeError(f"{what} takes a mapping or a path, not {type(value).__name__}")


def sign(
    input: Input,
    *,
    output_file: str | os.PathLike[str] | None = None,
    output_url: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """``typedstandards sign``: build and sign a record from an envelope input.

    ``output_file`` signs a file's bytes inline under ``raw-bytes/v1``; with ``output_url``, by
    reference as a BlobRef (``content_type`` names its type). Returns
    ``{package, envelopeHash, signature}``. The CLI reads the signing seed from its own
    environment, which it inherits from this process.
    """
    args, stdin = _input_args(input, "--input")
    if output_file is not None:
        args += ["--output-file", os.fspath(output_file)]
    if output_url is not None:
        args += ["--output-url", output_url]
    if content_type is not None:
        args += ["--content-type", content_type]
    return run("sign", args, stdin=stdin)


def withdraw(input: Input) -> dict[str, Any]:
    """``typedstandards withdraw``: sign an ``attestation/withdraws/v1``. Returns ``{node, nodeId, signature}``."""
    args, stdin = _input_args(input, "--input")
    return run("withdraw", args, stdin=stdin)


def attest(input: Input) -> dict[str, Any]:
    """``typedstandards attest``: sign a ``supersedes``, ``revises``, ``corroborates`` or ``contradicts``
    attestation. Returns ``{node, nodeId, signature}``."""
    args, stdin = _input_args(input, "--input")
    return run("attest", args, stdin=stdin)


def view(
    signed: Input,
    *,
    visibility: str,
    attestations: Iterable[Input] = (),
    trust_registry_url: str | None = None,
    package_url: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """``typedstandards view``: build the commitment view a host serves, with the package inline.

    ``signed`` is what :func:`sign` returned (or its path); each of ``attestations`` is what
    :func:`withdraw` or :func:`attest` returned (or its path). Mappings are written to temporary
    files, removed before this returns, since only one input can be standard input.
    """
    if isinstance(attestations, (Mapping, str, os.PathLike)):
        raise TypeError("attestations takes a list of attestations, not one")
    with tempfile.TemporaryDirectory(prefix="typedstandards-view-") as directory:
        args = ["--signed", _as_file(signed, directory, "signed.json", "signed"), "--visibility", visibility]
        for i, attestation in enumerate(attestations):
            args += ["--attestation", _as_file(attestation, directory, f"attestation-{i}.json", "attestations")]
        if trust_registry_url is not None:
            args += ["--trust-registry-url", trust_registry_url]
        if package_url is not None:
            args += ["--package-url", package_url]
        if title is not None:
            args += ["--title", title]
        return run("view", args)


def verify(
    input: Input,
    *,
    blobs: Iterable[str | os.PathLike[str]] = (),
    full: bool = True,
) -> dict[str, Any]:
    """``typedstandards verify``: verify what :func:`sign` or :func:`view` printed, offline.

    ``full`` (the default) passes ``--json``, so the result carries every check's fields
    (``checks``) and the lifecycle resolution (``lifecycle``) beside ``ok``, ``nodeId`` and
    ``failures``. ``blobs`` are local files for the record's BlobRefs. A record that does not
    verify raises :class:`~typedstandards.errors.VerificationError`, whose ``document`` is the
    verdict.
    """
    if isinstance(blobs, (str, os.PathLike)):
        raise TypeError("blobs takes a list of paths, not one")
    args, stdin = _input_args(input, "--input")
    for blob in blobs:
        args += ["--blob", os.fspath(blob)]
    if full:
        args.append("--json")
    return run("verify", args, stdin=stdin)
