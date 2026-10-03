"""``pin``: fetch a URL once, and record what was fetched as a retrieval entry for ``queries[]``.

This module is the one place the package computes a digest, and the guard tests allow it here
only. The SHA-256 is of the fetched body: a signed assertion in the record's ``queries[]`` that
no check recomputes (spec §8.7.5 item 7). It is none of the format's hashes: the content hash,
envelope hash and node id are the CLI's.

The entry follows the core-satellite example's ``queries[]`` retrieval shape
(``package/build.mjs`` lines 280-285 at ``b40c30f``)::

    {"tool": ..., "operationType": "retrieve",
     "arguments": {"url", "sha256", "bytes", "httpStatus", "fetchedAt", "licence"?, "rowsUpdatedAt"?},
     "datasetId"?: ...}

An open-data portal resource is recognised by its URL's shape, not its host:
``…/resource/<id>[.ext]`` or ``…/api/views/<id>/rows.<ext>``, with ``<id>`` matching
``[a-z0-9]{4}-[a-z0-9]{4}``. For one, ``pin`` also asks ``<origin>/api/views/<id>`` for the
dataset's ``rowsUpdatedAt`` (epoch seconds, as the portal reports it) and records it with the
``datasetId``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:  # httpx is imported inside pin(), so importing the package does not load it
    import httpx

#: The ``tool`` an entry names by default.
PIN_TOOL = "typedstandards.pin"

_PORTAL_PATH = re.compile(
    r"(?:/resource/(?P<a>[a-z0-9]{4}-[a-z0-9]{4})(?:\.[A-Za-z0-9]+)?|/api/views/(?P<b>[a-z0-9]{4}-[a-z0-9]{4})/rows\.[A-Za-z0-9]+)$"
)


class Pinned(NamedTuple):
    """What :func:`pin` returns: the fetched bytes, and the retrieval entry describing them."""

    content: bytes
    entry: dict[str, Any]


def portal_dataset_id(url: str) -> str | None:
    """The dataset id when ``url`` has an open-data portal resource's shape, else ``None``."""
    match = _PORTAL_PATH.search(urlsplit(url).path)
    return (match.group("a") or match.group("b")) if match else None


def _utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("the clock must return a timezone-aware datetime")
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _rows_updated_at(client: httpx.Client, url: str, dataset_id: str) -> Any:
    parts = urlsplit(url)
    meta_url = urlunsplit((parts.scheme, parts.netloc, f"/api/views/{dataset_id}", "", ""))
    response = client.get(meta_url, headers={"Accept": "application/json"})
    response.raise_for_status()
    try:
        value = response.json()["rowsUpdatedAt"]
    except (ValueError, KeyError, TypeError) as err:
        raise ValueError(
            f"{meta_url} did not report rowsUpdatedAt; pass portal_metadata=False if {url} is not a portal resource"
        ) from err
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{meta_url} reported rowsUpdatedAt {value!r}, not epoch seconds")
    return value


def pin(
    url: str,
    *,
    licence: str | None = None,
    dataset_id: str | None = None,
    portal_metadata: bool | None = None,
    tool: str = PIN_TOOL,
    save: str | os.PathLike[str] | None = None,
    client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
    timeout: float = 60.0,
) -> Pinned:
    """Fetch ``url`` and return ``Pinned(content, entry)``.

    ``content`` is the response body (after HTTP content decoding), so a notebook can read the
    pinned bytes from memory, for example ``pd.read_csv(io.BytesIO(content))``. ``entry`` is a
    retrieval entry for the record's ``queries[]``: ``tool``, ``operationType: "retrieve"``, and
    ``arguments`` with ``url`` (as given), ``sha256`` (hex, of ``content``), ``bytes`` (its
    length), ``httpStatus`` and ``fetchedAt`` (ISO 8601 UTC, when the response arrived);
    ``finalUrl`` when redirects led elsewhere; ``licence`` when given.

    For a URL with a portal resource's shape (``portal_metadata=None``, the default, decides by
    shape; ``True`` requires the shape; ``False`` skips it), a second request reads the portal's
    ``rowsUpdatedAt``, which is added to ``arguments``, and the dataset id becomes ``datasetId``.
    ``dataset_id`` sets ``datasetId`` for any URL. A response that is not 2xx raises
    ``httpx.HTTPStatusError``.

    ``save`` writes the bytes to that path and the entry, as JSON, beside it at
    ``<save>.pin.json``. ``client`` (used as given, not closed) or ``transport`` (for a client
    this call makes and closes) and ``clock`` (returns an aware ``datetime``) are for tests and
    for callers with their own HTTP settings.
    """
    import httpx

    portal_id = portal_dataset_id(url)
    if portal_metadata is True and portal_id is None:
        raise ValueError(
            f"{url} does not have a portal resource's shape (…/resource/<id> or …/api/views/<id>/rows.<ext>)"
        )
    read_portal = portal_id is not None and portal_metadata is not False
    now = clock or (lambda: datetime.now(UTC))

    own = client is None
    http = client if client is not None else httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
    try:
        response = http.get(url)
        fetched_at = _utc(now())
        response.raise_for_status()
        content = response.content
        rows_updated_at = _rows_updated_at(http, url, portal_id) if read_portal and portal_id else None
    finally:
        if own:
            http.close()

    arguments: dict[str, Any] = {
        "url": url,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "httpStatus": response.status_code,
        "fetchedAt": fetched_at,
    }
    if response.history:
        arguments["finalUrl"] = str(response.url)
    if licence is not None:
        arguments["licence"] = licence
    if rows_updated_at is not None:
        arguments["rowsUpdatedAt"] = rows_updated_at
    entry: dict[str, Any] = {"tool": tool, "operationType": "retrieve", "arguments": arguments}
    if dataset_id is not None or read_portal:
        entry["datasetId"] = dataset_id if dataset_id is not None else portal_id

    if save is not None:
        target = Path(save)
        target.write_bytes(content)
        Path(f"{target}.pin.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return Pinned(content, entry)
