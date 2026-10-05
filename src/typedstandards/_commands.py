"""The five pass-through commands: ``sign``, ``withdraw``, ``attest``, ``view``, ``verify``.

Each takes the CLI's inputs as Python values and returns the CLI's stdout parsed as JSON.
An input given as a mapping is written as JSON to a temporary file, whose path the CLI reads and
which is removed before the call returns; a ``str`` or ``os.PathLike`` is a path the CLI reads.
No input reaches the CLI through a pipe: CLI 0.2.0 reads ``--input -`` with a synchronous read
that fails with EAGAIN on a document larger than a pipe buffer holds (typedstandards#138). The
wrapper computes nothing the format defines: the CLI builds, signs, hashes and verifies.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ._cli import run

#: An input: a JSON object as a mapping, or the path of a JSON file.
Input = Mapping[str, Any] | str | os.PathLike[str]


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


@contextmanager
def _input_args(value: Input, flag: str) -> Iterator[list[str]]:
    """``[flag, path]`` for one input. A mapping is written to a temporary file, removed when the
    block exits, whether the CLI succeeded or not."""
    if isinstance(value, Mapping):
        with tempfile.TemporaryDirectory(prefix="typedstandards-input-") as directory:
            yield [flag, _as_file(value, directory, "input.json", flag)]
    elif isinstance(value, (str, os.PathLike)):
        yield [flag, os.fspath(value)]
    else:
        raise TypeError(f"{flag} takes a mapping (written to a temporary file) or a path, not {type(value).__name__}")


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
    with _input_args(input, "--input") as args:
        if output_file is not None:
            args += ["--output-file", os.fspath(output_file)]
        if output_url is not None:
            args += ["--output-url", output_url]
        if content_type is not None:
            args += ["--content-type", content_type]
        return run("sign", args)


def withdraw(input: Input) -> dict[str, Any]:
    """``typedstandards withdraw``: sign an ``attestation/withdraws/v1``. Returns ``{node, nodeId, signature}``."""
    with _input_args(input, "--input") as args:
        return run("withdraw", args)


def attest(input: Input) -> dict[str, Any]:
    """``typedstandards attest``: sign a ``supersedes``, ``revises``, ``corroborates`` or ``contradicts``
    attestation. Returns ``{node, nodeId, signature}``."""
    with _input_args(input, "--input") as args:
        return run("attest", args)


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
    files, removed before this returns.
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


def _without_trust_registry(value: Input) -> Input:
    """G0 D9 = A, typedstandards#136: CLI 0.2.0's verify exits 2 on a bundle's top-level
    ``trustRegistry``, which host-core inlines in every bundle it serves under a registry. Drop that
    one key from a bundle (a document with ``packageHash``) and change nothing else; any other
    document, and a bundle file without the key, reach the CLI as given. A bundle that loses the
    key reaches the CLI as a temporary file, like any mapping, also when it was given as a path.

    Remove this workaround when the wrapper pins a CLI whose verify accepts the key.
    """
    document: Any = value
    if not isinstance(value, Mapping):
        if not isinstance(value, (str, os.PathLike)):
            return value
        try:
            document = json.loads(Path(value).read_bytes())
        except (OSError, ValueError):
            return value  # the CLI reports an unreadable or malformed file
    if isinstance(document, Mapping) and "packageHash" in document and "trustRegistry" in document:
        return {key: item for key, item in document.items() if key != "trustRegistry"}
    return value


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
    verdict. A bundle's top-level ``trustRegistry`` is dropped before the CLI sees it
    (typedstandards#136); nothing else is changed.
    """
    if isinstance(blobs, (str, os.PathLike)):
        raise TypeError("blobs takes a list of paths, not one")
    with _input_args(_without_trust_registry(input), "--input") as args:
        for blob in blobs:
            args += ["--blob", os.fspath(blob)]
        if full:
            args.append("--json")
        return run("verify", args)
