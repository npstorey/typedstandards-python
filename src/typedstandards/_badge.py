"""``badge_cell``: the verifier badge as a notebook's first cell (Jupyter) or a ``mo.md`` cell (Marimo).

The link and the badge follow ``@typedstandards/host-core``'s ``links.ts`` (typedstandards
``116882a``, ``packages/host-core/src/links.ts``): ``buildVerifyHref`` (:42-48) puts a hosted
bundle URL through ``?url=`` percent-encoded with ``encodeURIComponent``, and
``buildEmbedMarkdown`` (:70-79) writes a linked image whose destination is in angle brackets.
The constants are copied from :15-28. ``tests/test_badge.py`` compares this module's output with
strings captured from host-core's own functions.

The cell is written before the notebook is signed, and under ``raw-bytes/v1`` the notebook's
bytes are the record's output, so the cell can carry only facts known by name before signing:
the badge linked to the bundle URL, the host and the capture method. It never carries a hash or
a time; the verifier shows those from the signed record. Spec §8.8.4 calls such a cell "purely a
reader affordance".
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote, unquote, urlsplit

from ._notebook import insert_cell, source_lines

#: host-core links.ts:16, the verifier's canonical origin.
CANONICAL_ORIGIN = "https://typedstandards.org"
#: links.ts:19.
BADGE_ASSET_PATH = "/badge/typed-standards-verify.svg"
#: links.ts:22-23.
BADGE_WIDTH = 248
BADGE_HEIGHT = 30
#: links.ts:28: it describes the action, not a verdict.
BADGE_ALT = "Verify this record with Typed Standards"

#: The characters ``encodeURIComponent`` leaves unescaped besides ASCII letters and digits.
_URI_COMPONENT_SAFE = "-_.!~*'()"

#: The badge cell's id (nbformat 4.5).
BADGE_CELL_ID = "typedstandards-badge"

_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_DATE_OR_TIME = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}(?::\d{2})?")
_UNSAFE_IN_TABLE = re.compile(r"[|`\\\"\x00-\x1f\x7f]")


def encode_uri_component(value: str) -> str:
    """JavaScript's ``encodeURIComponent``: UTF-8, every byte escaped but ``A-Z a-z 0-9 - _ . ! ~ * ' ( )``."""
    return quote(value, safe=_URI_COMPONENT_SAFE)


def verify_href(bundle_url: str) -> str:
    """The verifier deep link for a hosted bundle: ``https://typedstandards.org/verify?url=<encoded>``."""
    url = bundle_url.strip()
    if not re.match(r"https?://", url, re.IGNORECASE):
        raise ValueError(f"bundle_url must be an http(s) URL of a served bundle, not {bundle_url!r}")
    return f"{CANONICAL_ORIGIN}/verify?url={encode_uri_component(url)}"


def badge_markdown(bundle_url: str) -> str:
    """host-core's ``buildEmbedMarkdown`` for a hosted bundle (light theme)."""
    return f"[![{BADGE_ALT}]({CANONICAL_ORIGIN}{BADGE_ASSET_PATH})](<{verify_href(bundle_url)}>)"


def _check_fact(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if _UNSAFE_IN_TABLE.search(value):
        raise ValueError(
            f"{name} {value!r} holds a character the cell's table cannot carry (|, `, \\, \" or a control)"
        )
    return value.strip()


def refuse_hash_or_time(text: str, *, authorities: tuple[str, ...] = ()) -> str:
    """Raise ``ValueError`` when ``text`` holds a 64-hex string, a date or a time of day.

    The badge cell is part of the signed bytes, written before signing: a hash in it cannot be
    the record's own, and a time in it cannot be the signing time, so either would mislead.
    Each of ``authorities`` (a URL's host and port, as the text carries them) is left out of the
    date and time check, so ``192.168.1.10:8080`` is not read as the time ``10:80``.
    """
    if _HEX64.search(text):
        raise ValueError(
            "the badge cell would carry a 64-hex string; it is written before signing, so it names no hash"
        )
    scan = text
    for authority in authorities:
        if authority:
            scan = scan.replace(authority, " ")
    if _DATE_OR_TIME.search(scan):
        raise ValueError("the badge cell would carry a date or time; it is written before signing, so it names no time")
    return text


def badge_text(bundle_url: str, *, capture_method: str, host: str | None = None) -> str:
    """The badge cell's Markdown: the badge, a two-row table (host, capture method), one sentence."""
    url = bundle_url.strip()
    parts = urlsplit(url)
    if host is None:
        host = parts.netloc
    host = _check_fact("host", host)
    capture_method = _check_fact("capture_method", capture_method)
    text = (
        f"{badge_markdown(bundle_url)}\n"
        "\n"
        "| Typed Standards record | |\n"
        "|---|---|\n"
        f"| Host | `{host}` |\n"
        f"| Capture method | `{capture_method}` |\n"
        "\n"
        "This cell is a reader affordance and is not authoritative: verification reads the signed record, "
        "not this cell, and the verifier shows the record's signer, hash and time.\n"
    )
    # The cell carries the URL percent-encoded, which hides a time's ":"; so the URL past its
    # authority (path, query, fragment) is checked as written and decoded too.
    rest = url[len(parts.scheme) + 3 + len(parts.netloc) :]
    refuse_hash_or_time(f"{rest}\n{unquote(rest)}")
    return refuse_hash_or_time(text, authorities=(f"`{host}`", encode_uri_component(parts.netloc)))


def _marimo_source(markdown: str) -> str:
    """A Marimo cell's source that renders ``markdown`` with ``mo.md``."""
    if '"""' not in markdown and "\\" not in markdown and not markdown.endswith('"'):
        return f'mo.md(\n    """{markdown}"""\n)\n'
    return f"mo.md({markdown!r})\n"


def badge_cell(
    bundle_url: str,
    *,
    capture_method: str,
    notebook: str | os.PathLike[str] | None = None,
    host: str | None = None,
    marimo: bool = False,
    cell_id: str = BADGE_CELL_ID,
) -> str:
    """The verifier badge as a notebook cell, written before signing.

    ``bundle_url`` is where the record's bundle will be served (for example
    ``https://<host>/bundles/<name>.bundle.json``). ``capture_method`` is the record's
    ``captureMethod`` (for example ``script-run``). ``host`` defaults to the bundle URL's host.

    Jupyter (the default): with ``notebook``, the cell is inserted as the notebook's first cell,
    a markdown cell with id ``cell_id`` on nbformat 4.5 or later, and every other byte of the
    file is kept. Returns the cell's Markdown. An existing cell with the same id is refused, so
    a second call does not add a second badge.

    Marimo (``marimo=True``): returns the source of a cell that renders the same Markdown with
    ``mo.md``, to paste into the app. ``notebook`` is refused, since a Marimo app is Python
    source, not a notebook file.

    The cell names no hash and no time: a URL or fact holding a 64-hex string, a date or a time
    is refused with ``ValueError``.
    """
    text = badge_text(bundle_url, capture_method=capture_method, host=host)
    if marimo:
        if notebook is not None:
            raise ValueError("marimo=True returns a cell's source; it does not edit a notebook file")
        return _marimo_source(text)
    if notebook is not None:
        insert_cell(
            notebook,
            {"cell_type": "markdown", "metadata": {}, "source": source_lines(text)},
            where="first",
            cell_id=cell_id,
        )
    return text
