"""Acceptance 1: ``pin``.

Over ``httpx.MockTransport`` (the autouse guard fails any real connection), ``pin(url)`` returns
the bytes and a retrieval entry carrying ``url``, ``sha256``, ``bytes``, ``httpStatus`` and
``fetchedAt``; for a portal-shaped URL, a second request reads ``rowsUpdatedAt`` from
``/api/views/<id>``. The digest follows the body. The host is fictional (``data.example.org``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from support import analysis_input

import typedstandards
from typedstandards import Pinned, pin
from typedstandards.pin import portal_dataset_id

BODY = b"id,district,fare\n1,north,13.75\n2,south,9.50\n"
FIXED = datetime(2026, 10, 3, 12, 0, 0, 250000, tzinfo=UTC)
PORTAL_CSV = "https://data.example.org/resource/abcd-1234.csv"
ROWS_UPDATED_AT = 1790991539


def clock() -> datetime:
    return FIXED


def portal(body: bytes = BODY, *, rows_updated_at: object = ROWS_UPDATED_AT, seen: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        if request.url.path == "/api/views/abcd-1234":
            return httpx.Response(
                200,
                json={
                    "id": "abcd-1234",
                    "rowsUpdatedAt": rows_updated_at,
                    "viewLastModified": 1790991000,
                    "publicationDate": 1700000000,
                },
            )
        if request.url.path in {"/resource/abcd-1234.csv", "/api/views/abcd-1234/rows.csv", "/files/data.csv"}:
            return httpx.Response(200, content=body, headers={"content-type": "text/csv"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_returns_the_bytes_and_the_entry() -> None:
    url = "https://files.example.org/files/data.csv"
    result = pin(url, transport=portal(), clock=clock)
    assert isinstance(result, Pinned)
    content, entry = result
    assert content == BODY
    assert entry == {
        "tool": "typedstandards.pin",
        "operationType": "retrieve",
        "arguments": {
            "url": url,
            "sha256": hashlib.sha256(BODY).hexdigest(),
            "bytes": len(BODY),
            "httpStatus": 200,
            "fetchedAt": "2026-10-03T12:00:00.250Z",
        },
    }


def test_a_changed_body_changes_the_digest() -> None:
    url = "https://files.example.org/files/data.csv"
    first = pin(url, transport=portal(BODY), clock=clock).entry["arguments"]
    second = pin(url, transport=portal(BODY + b"3,east,4.00\n"), clock=clock).entry["arguments"]
    assert first["sha256"] != second["sha256"]
    assert second["sha256"] == hashlib.sha256(BODY + b"3,east,4.00\n").hexdigest()
    assert second["bytes"] == len(BODY) + len(b"3,east,4.00\n")


@pytest.mark.parametrize("body", [b"", b"x", BODY, bytes(range(256)) * 4], ids=["empty", "one", "csv", "binary"])
def test_the_digest_follows_the_body(body: bytes) -> None:
    content, entry = pin("https://files.example.org/files/data.csv", transport=portal(body), clock=clock)
    assert content == body
    assert entry["arguments"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["arguments"]["bytes"] == len(body)


@pytest.mark.parametrize(
    "url", [PORTAL_CSV, "https://data.example.org/api/views/abcd-1234/rows.csv"], ids=["resource", "rows"]
)
def test_a_portal_resource_carries_rows_updated_at(url: str) -> None:
    seen: list[str] = []
    content, entry = pin(url, transport=portal(seen=seen), clock=clock)
    assert content == BODY
    assert seen == [url, "https://data.example.org/api/views/abcd-1234"]
    assert entry["arguments"]["rowsUpdatedAt"] == ROWS_UPDATED_AT
    assert entry["datasetId"] == "abcd-1234"
    assert entry["arguments"]["sha256"] == hashlib.sha256(BODY).hexdigest()


def test_a_moved_portal_reads_as_a_different_entry() -> None:
    before = pin(PORTAL_CSV, transport=portal(BODY, rows_updated_at=ROWS_UPDATED_AT), clock=clock).entry
    after = pin(
        PORTAL_CSV, transport=portal(BODY + b"3,east,4.00\n", rows_updated_at=ROWS_UPDATED_AT + 86400), clock=clock
    ).entry
    assert before["arguments"]["sha256"] != after["arguments"]["sha256"]
    assert before["arguments"]["rowsUpdatedAt"] != after["arguments"]["rowsUpdatedAt"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://data.example.org/resource/abcd-1234.csv", "abcd-1234"),
        ("https://data.example.org/resource/abcd-1234.geojson", "abcd-1234"),
        ("https://data.example.org/resource/abcd-1234", "abcd-1234"),
        ("https://data.example.org/resource/abcd-1234.json?$limit=5", "abcd-1234"),
        ("https://other.example.net/api/views/a1b2-c3d4/rows.csv?accessType=DOWNLOAD", "a1b2-c3d4"),
        ("https://data.example.org/resource/ABCD-1234.csv", None),
        ("https://data.example.org/resource/abcd-12345.csv", None),
        ("https://data.example.org/api/views/abcd-1234", None),
        ("https://data.example.org/files/abcd-1234.csv", None),
    ],
)
def test_portal_shape_is_recognised_by_path_not_host(url: str, expected: str | None) -> None:
    assert portal_dataset_id(url) == expected


def test_portal_metadata_can_be_skipped_or_required() -> None:
    seen: list[str] = []
    entry = pin(PORTAL_CSV, transport=portal(seen=seen), clock=clock, portal_metadata=False).entry
    assert seen == [PORTAL_CSV]
    assert "rowsUpdatedAt" not in entry["arguments"] and "datasetId" not in entry
    with pytest.raises(ValueError, match="portal resource's shape"):
        pin("https://files.example.org/files/data.csv", transport=portal(), clock=clock, portal_metadata=True)


@pytest.mark.parametrize("value", [None, "1790991539", 1790991539.5, True])
def test_a_portal_without_epoch_rows_updated_at_is_refused(value: object) -> None:
    with pytest.raises(ValueError, match="rowsUpdatedAt"):
        pin(PORTAL_CSV, transport=portal(rows_updated_at=value), clock=clock)


def test_licence_and_dataset_id_are_the_callers() -> None:
    entry = pin(
        "https://files.example.org/files/data.csv",
        transport=portal(),
        clock=clock,
        licence="CC-BY-4.0",
        dataset_id="fares",
    ).entry
    assert entry["arguments"]["licence"] == "CC-BY-4.0"
    assert entry["datasetId"] == "fares"


def test_a_failed_fetch_raises() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        pin("https://files.example.org/missing.csv", transport=portal(), clock=clock)


def test_a_redirect_is_followed_and_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old.csv":
            return httpx.Response(301, headers={"location": "https://files.example.org/files/data.csv"})
        return httpx.Response(200, content=BODY)

    entry = pin("https://files.example.org/old.csv", transport=httpx.MockTransport(handler), clock=clock).entry
    assert entry["arguments"]["url"] == "https://files.example.org/old.csv"
    assert entry["arguments"]["finalUrl"] == "https://files.example.org/files/data.csv"
    assert entry["arguments"]["httpStatus"] == 200


def test_an_injected_client_is_used_and_left_open() -> None:
    with httpx.Client(transport=portal()) as client:
        content, _ = pin("https://files.example.org/files/data.csv", client=client, clock=clock)
        assert content == BODY
        assert not client.is_closed


def test_a_naive_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        pin("https://files.example.org/files/data.csv", transport=portal(), clock=lambda: datetime(2026, 10, 3))


def test_save_writes_the_bytes_and_the_entry(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    _, entry = pin(PORTAL_CSV, transport=portal(), clock=clock, save=target)
    assert target.read_bytes() == BODY
    written = (tmp_path / "data.csv.pin.json").read_text(encoding="utf-8")
    assert json.loads(written) == entry
    assert written.endswith("}\n")


def test_the_entry_is_signable_in_queries(seed: str) -> None:
    """The real CLI accepts the entry in a record's queries[] and signs it as given."""
    _, entry = pin(PORTAL_CSV, transport=portal(), clock=clock, licence="CC-BY-4.0")
    signed = typedstandards.sign(analysis_input(queries=[entry], output="a test output"))
    assert signed["package"]["queries"] == [entry]
