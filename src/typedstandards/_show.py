"""``show``: render a record and what the CLI's ``verify --json`` reported for it, as HTML.

``show`` renders and checks nothing itself. The record (a bundle ``view`` printed, or what
``sign`` printed) supplies the type, signer, hash, ``createdAt``, ``vcsRef``, ``summary`` and
``extensions``; the verify result (``{ok, nodeId, failures, checks, lifecycle}``) supplies every
check's reading and the lifecycle status. Without a result, ``show`` asks the CLI for one.

The labels follow hub ADR-0030 §10 (``docs/adr/0030-self-certifying-signer-did-key.md`` at
``6957a3a``, lines 131-147): a key-derived signer reads "Signed with a self-certifying key", in
the normal tier and never beside a check-mark; ``displayName`` and ``bindingTier`` are the
signer's own description; check #14's ``key_derived_match`` reads "Signer identifier matches the
signing key"; continuity is "the same key". No line carries a check-mark. One sentence states,
as spec §9.3 does, that this does not say the analysis is correct.

**The role** is a signed assertion the wrapper reads, not a check (Notebook Evidence D2). ``show``
reads it from the package's ``extensions`` at ``role_path`` (default ``("role",)``, that is
``extensions["role"]``), a string or a list of strings, and labels it as asserted by the signer.

Every string taken from the record or the result is HTML-escaped. The output depends only on
the inputs, so the same inputs give the same bytes.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from typing import Any

#: The one sentence spec §9.3 asks a verifier's display to carry, in this display's words.
NOT_CORRECTNESS = (
    "This shows that the record is intact and which key signed it; it does not say the analysis is correct."
)

#: ADR-0030 §10's label and detail for a self-certifying key.
SELF_CERTIFIED_LABEL = "Signed with a self-certifying key"
SELF_CERTIFIED_DETAIL = (
    "The signer's identifier is derived from the signing key, so it proves that the same key signed "
    "everything under this identifier, not who holds the key. No registry vouches for it, and the key "
    "cannot be rotated or revoked."
)
#: ADR-0030 §10's label for check #14's key_derived_match.
KEY_DERIVED_MATCH_LABEL = "Signer identifier matches the signing key"

_STRUCTURAL = frozenset(
    {
        "hashMatch",
        "recomputedHash",
        "nodeId",
        "kid",
        "hasSigning",
        "rekorVerified",
        "rekorDetails",
        "rekorInclusion",
        "rfc3161",
        "blobRefsVerified",
    }
)

_TABLE = "border-collapse: collapse; margin: 0.25em 0;"
_TH = "text-align: left; padding: 0.15em 1em 0.15em 0; vertical-align: top; font-weight: 600;"
_TD = "text-align: left; padding: 0.15em 0; vertical-align: top;"
_NOTE = "color: #555;"


class Shown:
    """What :func:`show` returns for Jupyter: an object whose ``_repr_html_`` is the HTML."""

    __slots__ = ("html",)

    def __init__(self, html: str) -> None:
        self.html = html

    def _repr_html_(self) -> str:
        return self.html

    def __repr__(self) -> str:
        return f"<typedstandards.Shown: {len(self.html)} characters of HTML; display it in a notebook>"


def _e(value: Any) -> str:
    """HTML-escape any value taken from the record or the result."""
    if isinstance(value, str):
        return escape(value, quote=True)
    return escape(json.dumps(value, ensure_ascii=False, sort_keys=True), quote=True)


def _code(value: Any, title: Any = None) -> str:
    attr = f' title="{_e(title)}"' if title is not None else ""
    return f"<code{attr}>{_e(value)}</code>"


def _note(text: str) -> str:
    return f'<span style="{_NOTE}">{text}</span>'


def _abbreviate(identifier: str) -> str:
    if identifier.startswith("did:key:") and len(identifier) > 24:
        key = identifier[len("did:key:") :]
        return f"did:key:{key[:8]}…{key[-6:]}"
    if len(identifier) > 40:
        return f"{identifier[:28]}…{identifier[-8:]}"
    return identifier


def _get(mapping: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(mapping, Mapping):
            return None
        mapping = mapping.get(key)
    return mapping


def _load(value: Mapping[str, Any] | str | os.PathLike[str]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    loaded = json.loads(Path(value).read_bytes())
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{os.fspath(value)} is not a JSON object")
    return loaded


def _role(package: Mapping[str, Any], role_path: Sequence[str]) -> str | None:
    value = _get(package.get("extensions"), *role_path)
    if isinstance(value, str) and value:
        return value
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return ", ".join(value)
    return None


def _status(lifecycle: Mapping[str, Any]) -> str:
    status = lifecycle.get("status")
    if status == "withdrawn":
        text = f"{_code('withdrawn')}, reason: {_e(lifecycle.get('withdrawnReason') or '(none given)')}"
        if lifecycle.get("withdrawnAt"):
            text += f" {_note('(at ' + _e(lifecycle['withdrawnAt']) + ')')}"
        return text
    if status == "superseded":
        successor = lifecycle.get("successorNodeId")
        text = f"{_code('superseded')}, successor: "
        text += _code(str(successor)[:12] + "…", successor) if successor else "(not named)"
        if lifecycle.get("supersededAt"):
            text += f" {_note('(at ' + _e(lifecycle['supersededAt']) + ')')}"
        return text
    if status is None:
        return _note("not reported")
    return _code(status)


def _check_rows(checks: Mapping[str, Any], package: Mapping[str, Any]) -> list[str]:
    rows: list[tuple[str, str]] = []

    def add(name: str, reading: str) -> None:
        rows.append((name, reading))

    def status_of(key: str) -> Any:
        return _get(checks, key, "status")

    if "envelopeIntegrity" in checks:
        add("#1 Envelope integrity", _code(status_of("envelopeIntegrity")))
    if "signatureValid" in checks:
        valid = checks["signatureValid"]
        add("#2 Signature", _code({True: "valid", False: "invalid"}.get(valid, "no signature")))
    if "contentCanonicalization" in checks:
        rule = _get(checks, "contentCanonicalization", "rule")
        add(
            "#3 Content canonicalization",
            _code(status_of("contentCanonicalization")) + (f", {_code(rule)}" if rule else ""),
        )
    if "contentHash" in checks:
        matched = _get(checks, "contentHash", "matched")
        add("#4 Content hash", _code(status_of("contentHash")) + (f", {_code(matched)}" if matched else ""))
    if "keyTrust" in checks:
        trust = status_of("keyTrust")
        if trust == "self_certified":
            add("#5 Key trust", f"{SELF_CERTIFIED_LABEL} {_note('(' + _code(trust) + '; no registry vouches for it)')}")
        else:
            verified = _get(checks, "keyTrust", "verified")
            add(
                "#5 Key trust",
                _code(trust) + (f" {_note('(verified: ' + _e(verified) + ')')}" if verified is not None else ""),
            )
    if "signingKeyIdConsistency" in checks:
        add("#6 Signing key id", _code(status_of("signingKeyIdConsistency")))
    if "hasTimestamp" in checks:
        rfc3161 = checks.get("rfc3161")
        if not checks["hasTimestamp"]:
            add("#7 Timestamp", _note("no RFC 3161 token carried"))
        else:
            add("#7 Timestamp", _code(_get(rfc3161, "status") or "token carried"))
    if "hasRekor" in checks:
        if not checks["hasRekor"]:
            add("#8 Transparency log", _note("no log entry carried"))
        else:
            add(
                "#8 Transparency log",
                _code({True: "verified", False: "not verified"}.get(checks.get("rekorVerified"), "entry carried")),
            )
    if "blobRefs" in checks:
        refs = checks["blobRefs"] if isinstance(checks["blobRefs"], list) else []
        if not refs:
            add("#9 Referenced files", _note("none"))
        else:
            readings = ", ".join(_code(_get(r, "status") or _get(r, "reason") or r) for r in refs)
            add("#9 Referenced files", f"{len(refs)}: {readings}")
    if "lifecycle" in checks:
        source = _get(checks, "lifecycle", "source")
        add(
            "#10 Lifecycle",
            _code(status_of("lifecycle")) + (f" {_note('(source: ' + _e(source) + ')')}" if source else ""),
        )
    capture = _get(checks, "captureMethodVocab", "captureMethod") or _get(package, "metadata", "captureMethod")
    if capture:
        add("#11 Capture method", _code(capture))
    if "typeResolution" in checks:
        add("#12 Type", _code(status_of("typeResolution")) + f", {_code(_get(checks, 'typeResolution', 'type'))}")
    if "signerIdentity" in checks:
        identity = status_of("signerIdentity")
        if identity == "key_derived_match":
            add("#14 Signer identity", f"{KEY_DERIVED_MATCH_LABEL} {_note('(' + _code(identity) + ')')}")
        else:
            add("#14 Signer identity", _code(identity))
    if "captureMethodVocab" in checks:
        profile = _get(checks, "captureMethodVocab", "profileType")
        add(
            "#15 Capture method vocabulary",
            _code(status_of("captureMethodVocab")) + (f", {_code(profile)}" if profile else ""),
        )
    if "contentProfile" in checks:
        add("#16 Content profile", _code(status_of("contentProfile")))

    known = {
        "envelopeIntegrity", "signatureValid", "contentCanonicalization", "contentHash", "keyTrust",
        "signingKeyIdConsistency", "hasTimestamp", "hasRekor", "blobRefs", "lifecycle", "typeResolution",
        "signerIdentity", "captureMethodVocab", "contentProfile",
    }  # fmt: skip
    for key in sorted(k for k in checks if k not in known and k not in _STRUCTURAL):
        value = checks[key]
        add(_e(key), _code(_get(value, "status") if isinstance(value, Mapping) and "status" in value else value))
    return [f"<li>{name}: {reading}</li>" for name, reading in rows]


def render(
    record: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    role_path: Sequence[str] = ("role",),
) -> str:
    """The HTML for ``record`` and its verify ``result``."""
    package = record.get("package")
    if not isinstance(package, Mapping):
        raise ValueError("show takes what view or sign printed: a record with its package inline")
    checks = result.get("checks") if isinstance(result.get("checks"), Mapping) else {}
    signer = package.get("signer") if isinstance(package.get("signer"), Mapping) else {}
    identifier = signer.get("identifier")
    key_status = _get(checks, "keyTrust", "status")
    record_hash = record.get("packageHash") or record.get("envelopeHash")
    node_id = result.get("nodeId") or record_hash

    rows: list[tuple[str, str]] = []
    record_type = package.get("type") or _get(checks, "typeResolution", "type")
    rows.append(("Type", _code(record_type) if record_type else _note("none named; read as content/analysis/v1")))
    role = _role(package, role_path)
    where = "extensions" + "".join(f"[{json.dumps(k)}]" for k in role_path)
    rows.append(
        (
            "Role",
            f"{_e(role)} {_note('(asserted by the signer in ' + _e(where) + '; not checked)')}"
            if role
            else _note(f"none asserted in {_e(where)}"),
        )
    )
    rows.append(("Status", _status(result.get("lifecycle") or {})))

    if isinstance(identifier, str):
        signer_cell = _code(_abbreviate(identifier), identifier)
        if key_status == "self_certified":
            signer_cell += f" · {SELF_CERTIFIED_LABEL}<br>{_note(SELF_CERTIFIED_DETAIL)}"
        elif key_status:
            signer_cell += f" · key status {_code(key_status)}"
    else:
        signer_cell = _note("no signer identifier in the record")
    rows.append(("Signer", signer_cell))
    if signer.get("displayName"):
        rows.append(
            (
                "Name",
                f"calls itself “{_e(signer['displayName'])}” " + _note("(the signer’s own description; not verified)"),
            )
        )
    if signer.get("bindingTier"):
        rows.append(
            (
                "Binding tier",
                f"describes itself as {_code(signer['bindingTier'])} "
                + _note("(the signer’s own description; no check establishes it)"),
            )
        )
    if node_id:
        rows.append(("Envelope hash", _code(str(node_id)[:12] + "…", node_id)))
        if record_hash and node_id != record_hash:
            rows.append(("Record names", _code(str(record_hash)[:12] + "…", record_hash)))
    created = _get(package, "metadata", "createdAt")
    if created:
        rows.append(("Created", _code(created) + f" {_note('(the signer’s clock)')}"))
    vcs = package.get("vcsRef")
    if isinstance(vcs, Mapping):
        parts = [_code(vcs.get("repoUrl"))]
        if vcs.get("commitSha"):
            parts.append(f"commit {_code(vcs['commitSha'])}")
        if vcs.get("path"):
            parts.append(f"path {_code(vcs['path'])}")
        if vcs.get("ref"):
            parts.append(f"ref {_code(vcs['ref'])}")
        rows.append(("Source revision", ", ".join(parts) + f" {_note('(asserted; not fetched)')}"))
    summary = package.get("summary")
    if isinstance(summary, str) and summary:
        rows.append(("Summary", f"{_e(summary)} {_note('(the signer’s)')}"))

    if result.get("ok") is True:
        verdict = f"{_code('verify')}: ok, no check contradicts the record"
    else:
        failures = result.get("failures") or []
        listed = ", ".join(_code(f) for f in failures) if failures else _note("none listed")
        verdict = f"{_code('verify')}: failed, {listed}"

    title = record.get("subjectTitle")
    heading = "Typed Standards record" + (f": {_e(title)}" if isinstance(title, str) and title else "")
    table = "".join(f'<tr><th style="{_TH}">{name}</th><td style="{_TD}">{cell}</td></tr>' for name, cell in rows)
    checks_html = "".join(_check_rows(checks, package))
    return (
        '<div class="typedstandards-show" style="font-family: system-ui, sans-serif; line-height: 1.4;">'
        f'<p style="margin: 0 0 0.25em 0;"><strong>{heading}</strong></p>'
        f'<table style="{_TABLE}">{table}</table>'
        f'<p style="margin: 0.5em 0 0.1em 0;">{verdict}</p>'
        f'<ul style="margin: 0.1em 0 0.5em 1.2em; padding: 0;">{checks_html}</ul>'
        f'<p style="margin: 0;">{NOT_CORRECTNESS}</p>'
        "</div>"
    )


def show(
    record: Mapping[str, Any] | str | os.PathLike[str],
    result: Mapping[str, Any] | str | os.PathLike[str] | None = None,
    *,
    role_path: Sequence[str] = ("role",),
    marimo: bool = False,
) -> Any:
    """Render ``record`` with what ``verify --json`` reported for it.

    ``record`` is what :func:`~typedstandards.view` printed (a bundle) or what
    :func:`~typedstandards.sign` printed, as a mapping or the path of its JSON. ``result`` is a
    verify result for it (``typedstandards.verify(record)``, or a saved one); without it, ``show``
    runs :func:`~typedstandards.verify`, which needs Node, and renders a failed verdict too.

    Jupyter (the default) returns a :class:`Shown`, whose ``_repr_html_`` is the HTML. Marimo
    (``marimo=True``) returns ``mo.Html`` of the same HTML; ``marimo`` is imported only then.
    ``role_path`` names where the role sits under the package's ``extensions``.
    """
    loaded = _load(record)
    if result is None:
        from ._commands import verify
        from .errors import VerificationError

        try:
            verdict: Mapping[str, Any] = verify(dict(loaded))
        except VerificationError as err:
            if not isinstance(err.document, Mapping):
                raise
            verdict = err.document
    else:
        verdict = _load(result)
    html = render(loaded, verdict, role_path=role_path)
    if marimo:
        import marimo as mo

        return mo.Html(html)
    return Shown(html)
