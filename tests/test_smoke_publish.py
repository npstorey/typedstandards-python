"""``scripts/smoke_publish.py``, the live publish check for gate G3, run here against the fake
GitHub API over ``httpx.MockTransport``: never live. It signs through the vendored CLI with the
test seed in the environment, publishes under the default name, prints the receipt's fields and
nothing secret, and exits non-zero on a refusal."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from github_stub import FakeGitHub, dumps, manifest, policy
from publish_support import TOKEN
from support import analysis_input

import typedstandards as ts

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import smoke_publish  # noqa: E402


def fake_host(signer: str, origin: str = smoke_publish.ORIGIN) -> FakeGitHub:
    files = {"host.json": dumps(manifest(origin)), "host-policy.json": dumps(policy(signer))}
    return FakeGitHub(files, token=TOKEN, repository=smoke_publish.REPOSITORY)


@pytest.fixture
def signer(seed: str) -> str:
    """The test seed's did:key, as the CLI derives it."""
    return ts.sign(analysis_input(output="x"))["package"]["signer"]["identifier"]


def test_the_publish_check_publishes_one_record(
    signer: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ts.TOKEN_VARIABLE, TOKEN)
    gh = fake_host(signer)
    assert smoke_publish.main([], transport=gh.transport()) == 0
    out = capsys.readouterr().out
    print(out)
    assert "written: True" in out and "publish check passed" in out
    assert f"bundle_url: {smoke_publish.ORIGIN}/bundles/publish-check/" in out
    assert "run: None" in out
    assert TOKEN not in out and TOKEN[len("github_pat_") :] not in out
    assert [m for m, _ in gh.requests].count("PATCH") == 1
    assert any(p.startswith("records/publish-check/") for p in gh.files_at())


def test_the_publish_check_exits_non_zero_on_a_refusal(
    signer: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ts.TOKEN_VARIABLE, TOKEN)
    gh = fake_host("did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK")
    assert smoke_publish.main([], transport=gh.transport()) == 2
    assert "refused, nothing written" in capsys.readouterr().out
    assert gh.writes() == []

    monkeypatch.setenv(ts.TOKEN_VARIABLE, "op://Example Vault/example item/credential")
    assert smoke_publish.main([], transport=fake_host(signer).transport()) == 2
    assert "op://" in capsys.readouterr().out


def test_the_publish_check_names_another_origin(
    signer: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ts.TOKEN_VARIABLE, TOKEN)
    gh = fake_host(signer, origin="https://other.example.org")
    assert smoke_publish.main([], transport=gh.transport()) == 5
    assert "is not under" in capsys.readouterr().out
