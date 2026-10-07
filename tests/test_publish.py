"""``publish`` and ``publish_attestation`` (typedstandards#141 P2, acceptance 1 and 3).

Every test drives a fake GitHub API (``scripts/github_stub.py``) through ``httpx.MockTransport``;
the autouse guard fails any real connection. The host's files start as the template's
``host.json`` and ``host-policy.json`` at ``70bfd18`` (``fixtures/template-host*.json``), with the
policy's signer set to the test key and ``notebook`` added to the active rule, as P1 changes the
template. The records are signed by the vendored CLI under fresh seeds (``docs``, ``conftest.py``).

Every refusal is asserted to happen before any write request: no POST, PATCH, PUT or DELETE
reaches the transport.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from github_stub import FakeGitHub, dumps  # publish_support puts scripts/ on the path
from publish_support import ORIGIN, TOKEN, Docs, github, host, template_manifest, template_policy
from support import FIXTURES

import typedstandards as ts

WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def paths(gh: FakeGitHub, head: str) -> list[tuple[str, str]]:
    """The requests a publish of a new record makes, from the branch head ``head``."""
    r = f"/repos/{gh.repository}"
    return [
        ("GET", f"{r}/git/ref/heads/main"),
        ("GET", f"{r}/git/commits/{head}"),
        ("GET", f"{r}/contents/host.json"),
        ("GET", f"{r}/contents/host-policy.json"),
    ]


def writes(gh: FakeGitHub, blobs: int) -> list[tuple[str, str]]:
    r = f"/repos/{gh.repository}"
    return [("POST", f"{r}/git/blobs")] * blobs + [
        ("POST", f"{r}/git/trees"),
        ("POST", f"{r}/git/commits"),
        ("PATCH", f"{r}/git/refs/heads/main"),
    ]


def assert_nothing_written(gh: FakeGitHub) -> None:
    assert [r for r in gh.requests if r[0] in WRITE_METHODS] == []


def assert_git_data_only(gh: FakeGitHub) -> None:
    """Acceptance 3: no PUT or DELETE, and no write to the contents API."""
    for method, path in gh.requests:
        assert method in {"GET", "POST", "PATCH"}, (method, path)
        if method != "GET":
            assert "/contents/" not in path, (method, path)
            assert "/git/" in path, (method, path)


def default_name(signed: dict[str, Any], stem: str = "dog-licensing") -> str:
    return f"{stem}/{signed['package']['metadata']['createdAt'][:10]}-{signed['envelopeHash'][:8]}"


# --- a new record ---------------------------------------------------------------------------------


def test_a_new_record_is_two_blobs_one_tree_one_commit_and_one_fast_forward(docs: Docs) -> None:
    gh = github(docs)
    start = gh.head
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")

    assert gh.requests == paths(gh, start) + writes(gh, blobs=2)
    assert_git_data_only(gh)
    commit = gh.commits[gh.head]
    assert commit["parents"] == [start]
    files = gh.files_at()
    assert json.loads(files["records/dog-licensing.signed.json"]) == docs.first
    manifest = json.loads(files["host.json"])
    before = template_manifest()
    assert {k: v for k, v in manifest.items() if k != "records"} == {k: v for k, v in before.items() if k != "records"}
    assert manifest["records"] == before["records"] + [
        {
            "name": "dog-licensing",
            "signed": "records/dog-licensing.signed.json",
            "attestations": [],
            "title": "Dog licensing",
            "extensions": {"role": "notebook"},
        }
    ]
    assert files["host.json"].endswith(b"}\n") and b'\n  "origin"' in files["host.json"]
    bundle_url = f"{ORIGIN}/bundles/dog-licensing.bundle.json"
    assert receipt == {
        "name": "dog-licensing",
        "commit": gh.head,
        "bundle_url": bundle_url,
        "verify_url": "https://typedstandards.org/verify?url=" + bundle_url.replace(":", "%3A").replace("/", "%2F"),
        "registry_url": f"{ORIGIN}/.well-known/typed-publisher.json",
        "written": True,
        "run": None,
    }


def test_the_receipts_verify_url_is_the_badges_link(docs: Docs) -> None:
    from typedstandards._badge import verify_href

    gh = github(docs)
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert receipt["verify_url"] == verify_href(receipt["bundle_url"])


def test_the_default_name_is_the_stem_the_date_and_eight_hex(docs: Docs) -> None:
    gh = github(docs)
    receipt = ts.publish(docs.first, host=host(gh), notebook="work/dog-licensing.ipynb", title="Dog licensing")
    assert receipt["name"] == default_name(docs.first)
    assert f"records/{default_name(docs.first)}.signed.json" in gh.files_at()


def test_a_rerun_under_the_default_name_gets_a_new_name(docs: Docs) -> None:
    gh = github(docs)
    first = ts.publish(docs.first, host=host(gh), notebook="dog-licensing.ipynb", title="Dog licensing")
    second = ts.publish(docs.second, host=host(gh), notebook="dog-licensing.ipynb", title="Dog licensing")
    assert first["name"] != second["name"] and second["written"] is True
    assert [r["name"] for r in gh.json_at("host.json")["records"]][-2:] == [first["name"], second["name"]]


def test_a_signed_file_path_is_published_as_its_bytes(docs: Docs, tmp_path: Path) -> None:
    path = tmp_path / "first.signed.json"
    path.write_bytes(json.dumps(docs.first).encode())
    gh = github(docs)
    ts.publish(path, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert gh.files_at()["records/dog-licensing.signed.json"] == path.read_bytes()


def test_name_and_notebook_are_one_or_the_other(docs: Docs) -> None:
    gh = github(docs)
    with pytest.raises(TypeError, match="name= or notebook="):
        ts.publish(docs.first, host=host(gh), title="Dog licensing")
    with pytest.raises(TypeError, match="not both"):
        ts.publish(docs.first, host=host(gh), name="a", notebook="a.ipynb", title="Dog licensing")
    assert gh.requests == []


# --- a listed hash, a listed name -------------------------------------------------------------


def test_a_listed_hash_writes_nothing(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    start = gh.head
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert receipt["written"] is False and receipt["commit"] is None and receipt["name"] == "dog-licensing"
    assert gh.head == start
    assert_nothing_written(gh)
    assert gh.requests[-1] == ("GET", f"/repos/{gh.repository}/contents/records/dog-licensing.signed.json")


def test_a_repeated_publish_writes_once(docs: Docs) -> None:
    gh = github(docs)
    assert ts.publish(docs.first, host=host(gh), notebook="dog-licensing.ipynb", title="T")["written"] is True
    count = len(gh.writes())
    assert ts.publish(docs.first, host=host(gh), notebook="dog-licensing.ipynb", title="T")["written"] is False
    assert len(gh.writes()) == count


def test_a_listed_name_with_another_hash_is_refused_without_revises(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    with pytest.raises(ts.PublishRefusedError, match="dog-licensing is listed with another record"):
        ts.publish(docs.second, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert_nothing_written(gh)


def test_a_listed_name_with_another_hash_is_written_with_revises(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    start = gh.head
    receipt = ts.publish(
        docs.second, host=host(gh), name="dog-licensing", title="Dog licensing, rerun", revises=docs.revises
    )

    derived = f"dog-licensing-{docs.second['envelopeHash'][:8]}"
    assert receipt["name"] == derived and receipt["written"] is True
    r = f"/repos/{gh.repository}"
    assert gh.requests == paths(gh, start) + [("GET", f"{r}/contents/records/dog-licensing.signed.json")] + writes(
        gh, blobs=3
    )
    assert_git_data_only(gh)
    assert gh.commits[gh.head]["parents"] == [start]
    files = gh.files_at()
    node_path = f"records/dog-licensing.revises-{docs.revises['nodeId'][:8]}.json"
    assert json.loads(files[node_path]) == docs.revises
    assert json.loads(files[f"records/{derived}.signed.json"]) == docs.second
    entries = {e["name"]: e for e in json.loads(files["host.json"])["records"]}
    assert entries["dog-licensing"]["attestations"] == [node_path]
    assert entries[derived]["attestations"] == []
    assert entries[derived]["title"] == "Dog licensing, rerun"


def test_a_repeated_revise_writes_nothing(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    kwargs = {"name": "dog-licensing", "title": "Rerun", "revises": docs.revises}
    ts.publish(docs.second, host=host(gh), **kwargs)
    count = len(gh.writes())
    assert ts.publish(docs.second, host=host(gh), **kwargs)["written"] is False
    assert len(gh.writes()) == count


def test_revises_under_the_default_name_goes_on_its_targets_entry(docs: Docs) -> None:
    gh = github(docs, listed={default_name(docs.first): docs.first})
    receipt = ts.publish(
        docs.second, host=host(gh), notebook="dog-licensing.ipynb", title="Rerun", revises=docs.revises
    )
    assert receipt["name"] == default_name(docs.second)
    entries = {e["name"]: e for e in gh.json_at("host.json")["records"]}
    node_path = f"records/{default_name(docs.first)}.revises-{docs.revises['nodeId'][:8]}.json"
    assert entries[default_name(docs.first)]["attestations"] == [node_path]
    assert len([r for r in gh.requests if r[0] == "PATCH"]) == 1


@pytest.mark.parametrize("case", ["not a revises node", "another successor", "another target"])
def test_revises_whose_fields_do_not_match_is_refused(docs: Docs, case: str) -> None:
    node = {
        "not a revises node": docs.withdrawal,
        "another successor": docs.revises,
        "another target": docs.revises,
    }[case]
    signed = docs.first if case == "another successor" else docs.second
    listed = {"dog-licensing": docs.foreign if case == "another target" else docs.first}
    gh = github(docs, listed=listed)
    with pytest.raises(ts.PublishRefusedError, match="revises"):
        ts.publish(signed, host=host(gh), name="dog-licensing", title="Rerun", revises=node)
    assert_nothing_written(gh)


def test_revises_with_no_listed_target_is_refused(docs: Docs) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="no record this host lists"):
        ts.publish(docs.second, host=host(gh), notebook="dog-licensing.ipynb", title="Rerun", revises=docs.revises)
    assert_nothing_written(gh)


# --- names --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["records", "records/dog-licensing", "notes/evidence/x", "a/b/records"])
def test_a_name_with_a_records_or_evidence_segment_is_refused(docs: Docs, name: str) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="records|evidence"):
        ts.publish(docs.first, host=host(gh), name=name, title="Dog licensing")
    assert gh.requests == []


@pytest.mark.parametrize("name", ["", "dog licensing", "../x", "x/../y", "x/./y", "a//b", "x/", "/x", "café", "a:b"])
def test_a_name_failing_host_cores_rule_is_refused(docs: Docs, name: str) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="segments of letters, digits"):
        ts.publish(docs.first, host=host(gh), name=name, title="Dog licensing")
    assert gh.requests == []


def test_a_notebook_stem_failing_the_rule_is_refused(docs: Docs) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="segments of letters, digits"):
        ts.publish(docs.first, host=host(gh), notebook="Dog licensing.ipynb", title="Dog licensing")
    assert gh.requests == []


def test_an_origin_with_a_records_segment_is_refused(docs: Docs) -> None:
    manifest = template_manifest()
    manifest["origin"] = "https://example-owner.github.io/records"
    gh = github(docs, manifest=manifest)
    with pytest.raises(ts.PublishRefusedError, match="records"):
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert_nothing_written(gh)


# --- the record, the signer, the role, the title ---------------------------------------------------


def test_a_blobref_output_is_refused(docs: Docs) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="BlobRef"):
        ts.publish(docs.blobref, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert gh.requests == []


@pytest.mark.parametrize(
    "value",
    [{"package": {}, "envelopeHash": "0" * 64}, {"package": {}, "envelopeHash": "XYZ", "signature": {}}, ["x"]],
)
def test_a_document_sign_did_not_print_is_refused(docs: Docs, value: Any) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="what sign prints|envelopeHash"):
        ts.publish(value, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert gh.requests == []


def test_a_signer_other_than_the_policys_is_refused(docs: Docs) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="signer"):
        ts.publish(docs.foreign, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert_nothing_written(gh)


@pytest.mark.parametrize("role", ["claim", "note-book"])
def test_a_role_no_active_rule_admits_is_refused(docs: Docs, role: str) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match=f"no active rule .* admits the role {role}"):
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing", role=role)
    assert_nothing_written(gh)


def test_a_role_only_a_withdrawn_rule_admits_is_refused(docs: Docs) -> None:
    value = template_policy(docs.signer)
    value["display"] = [
        {"status": "active", "extensions": {"role": ["note"]}, "as": "current"},
        {"status": "withdrawn", "extensions": {"role": ["notebook"]}, "as": "withdrawn"},
    ]
    gh = github(docs, policy=value)
    with pytest.raises(ts.PublishRefusedError, match="admits the role notebook"):
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert_nothing_written(gh)


def test_the_template_policy_as_shipped_refuses_the_default_role(docs: Docs) -> None:
    """At 70bfd18 the active rule admits note only; P1 adds notebook (G0-3)."""
    value = json.loads((FIXTURES / "template-host-policy.json").read_text(encoding="utf-8"))
    value["signer"] = docs.signer
    gh = github(docs, policy=value)
    with pytest.raises(ts.PublishRefusedError, match="admits the role notebook"):
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing", role="note")
    assert receipt["written"] is True


def test_a_type_the_policy_does_not_name_is_refused(docs: Docs) -> None:
    value = template_policy(docs.signer)
    value["type"] = "content/claim/v1"
    gh = github(docs, policy=value)
    with pytest.raises(ts.PublishRefusedError, match="type"):
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert_nothing_written(gh)


@pytest.mark.parametrize("title", ["", "   "])
def test_an_empty_title_is_refused(docs: Docs, title: str) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="title"):
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title=title)
    assert gh.requests == []


# --- the ref update --------------------------------------------------------------------------------


def test_a_non_fast_forward_is_retried_once_after_rereading_the_head(docs: Docs) -> None:
    gh = github(docs)
    start = gh.head
    gh.concurrent_writes = 1
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    moved = gh.commits[gh.head]["parents"][0]
    r = f"/repos/{gh.repository}"
    assert gh.requests == (
        paths(gh, start)
        + writes(gh, blobs=2)
        + [("GET", f"{r}/git/ref/heads/main")]
        + paths(gh, moved)[1:]
        + writes(gh, blobs=2)
    )
    assert receipt["written"] is True and receipt["commit"] == gh.head
    assert gh.commits[moved]["message"] == "another writer"
    assert "other/" in "".join(gh.files_at())  # the other writer's file is kept


def test_a_second_non_fast_forward_is_an_error(docs: Docs) -> None:
    gh = github(docs)
    gh.concurrent_writes = 2
    with pytest.raises(ts.PublishError, match="not a fast forward") as caught:
        ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert not isinstance(caught.value, ts.PublishRefusedError)
    assert [m for m, _ in gh.requests].count("PATCH") == 2
    assert gh.requests[-1] == ("GET", f"/repos/{gh.repository}/git/ref/heads/main")
    assert "dog-licensing" not in json.dumps([e["name"] for e in gh.json_at("host.json")["records"]])


def test_a_ref_update_that_errored_but_landed_is_not_retried(docs: Docs) -> None:
    gh = github(docs)
    gh.landed_but_failed = [502]
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert [m for m, _ in gh.requests].count("PATCH") == 1
    assert gh.requests[-1] == ("GET", f"/repos/{gh.repository}/git/ref/heads/main")
    assert receipt["written"] is True and receipt["commit"] == gh.head


def test_a_non_fast_forward_retry_sees_a_record_another_writer_listed(docs: Docs) -> None:
    gh = github(docs)

    def other_writer_publishes_the_same(request: Any) -> None:
        if request.method == "PATCH" and gh.hook is not None:
            gh.hook = None
            files = dict(gh.files_at())
            manifest = json.loads(files["host.json"])
            manifest["records"].append(
                {
                    "name": "dog-licensing",
                    "signed": "records/dog-licensing.signed.json",
                    "attestations": [],
                    "title": "T",
                }
            )
            files["host.json"] = dumps(manifest)
            files["records/dog-licensing.signed.json"] = dumps(docs.first)
            tree, commit = gh._id("t"), gh._id("c")
            gh.trees[tree] = files
            gh.commits[commit] = {"tree": tree, "parents": [gh.head], "message": "another writer"}
            gh.head = commit
        return None

    gh.hook = other_writer_publishes_the_same
    receipt = ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert receipt["written"] is False and gh.commits[gh.head]["message"] == "another writer"
    assert [m for m, _ in gh.requests].count("PATCH") == 1


def test_an_api_error_names_the_request_and_githubs_message(docs: Docs) -> None:
    gh = github(docs)
    bad = ts.GitHubPagesHost(gh.repository, token=TOKEN + "x", transport=gh.transport())
    with pytest.raises(ts.PublishError, match=r"GET .*/git/ref/heads/main answered 401: Bad credentials"):
        ts.publish(docs.first, host=bad, name="dog-licensing", title="Dog licensing")
    assert_nothing_written(gh)


# --- publish_attestation -----------------------------------------------------------------------


def test_a_withdrawal_is_one_commit_on_its_records_entry(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    start = gh.head
    receipt = ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")
    r = f"/repos/{gh.repository}"
    assert gh.requests == paths(gh, start) + [("GET", f"{r}/contents/records/dog-licensing.signed.json")] + writes(
        gh, blobs=2
    )
    assert_git_data_only(gh)
    node_path = f"records/dog-licensing.withdraws-{docs.withdrawal['nodeId'][:8]}.json"
    assert json.loads(gh.files_at()[node_path]) == docs.withdrawal
    entry = next(e for e in gh.json_at("host.json")["records"] if e["name"] == "dog-licensing")
    assert entry["attestations"] == [node_path]
    assert receipt["name"] == "dog-licensing" and receipt["written"] is True and receipt["commit"] == gh.head
    assert receipt["bundle_url"] == f"{ORIGIN}/bundles/dog-licensing.bundle.json"


def test_a_listed_attestation_writes_nothing(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")
    count = len(gh.writes())
    assert ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")["written"] is False
    assert len(gh.writes()) == count


def test_a_claim_to_claim_node_is_refused(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    with pytest.raises(ts.PublishRefusedError, match="claim-to-claim"):
        ts.publish_attestation(docs.corroboration, host=host(gh), name="dog-licensing")
    assert gh.requests == []


def test_an_attestation_aimed_at_another_record_is_refused(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.second})
    with pytest.raises(ts.PublishRefusedError, match="targetNodeId"):
        ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")
    assert_nothing_written(gh)


def test_an_attestation_for_an_unlisted_name_is_refused(docs: Docs) -> None:
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="lists no record named dog-licensing"):
        ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")
    assert_nothing_written(gh)


def test_an_attestation_by_another_signer_is_refused(docs: Docs) -> None:
    gh = github(
        docs,
        listed={"dog-licensing": docs.first},
        policy=template_policy(docs.foreign["package"]["signer"]["identifier"]),
    )
    with pytest.raises(ts.PublishRefusedError, match="signer"):
        ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")
    assert_nothing_written(gh)


# --- acceptance 3 ---------------------------------------------------------------------------------


def test_every_write_is_a_git_data_call(docs: Docs) -> None:
    gh = github(docs, listed={"dog-licensing": docs.first})
    gh.concurrent_writes = 1
    ts.publish(docs.second, host=host(gh), name="dog-licensing", title="Rerun", revises=docs.revises)
    ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")
    ts.publish(docs.first, host=host(gh), notebook="dog-licensing.ipynb", title="Again")
    assert_git_data_only(gh)
    assert {m for m, _ in gh.requests} == {"GET", "POST", "PATCH"}
    patches = [m for m, _ in gh.requests].count("PATCH")
    commits = gh.requests.count(("POST", f"/repos/{gh.repository}/git/commits"))
    assert commits == patches == 4  # one commit per ref update: three calls, one of them retried


def test_the_source_writes_through_the_git_data_api_only() -> None:
    """No module sends a PUT or a DELETE, and the contents API is only read (a GET)."""
    for path in sorted((Path(ts.__file__).parent).glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for word in ('"PUT"', "'PUT'", '"DELETE"', "'DELETE'", ".put(", ".delete("):
            assert word not in source, (path.name, word)
        for number, line in enumerate(source.splitlines(), 1):
            if "/contents/" in line and not line.lstrip().startswith("#"):
                assert '"GET"' in line, f"{path.name}:{number}: {line.strip()}"


def test_a_policy_document_copy_is_not_changed(docs: Docs) -> None:
    gh = github(docs)
    before = copy.deepcopy(gh.files_at()["host-policy.json"])
    ts.publish(docs.first, host=host(gh), name="dog-licensing", title="Dog licensing")
    assert gh.files_at()["host-policy.json"] == before


# --- fixture provenance ---------------------------------------------------------------------------

TEMPLATE_PINNED = {
    "template-host.json": "8a80c9ea344196ac2b27b3a91eb3439f9217e72c5491b18540d253925b28a6fe",
    "template-host-policy.json": "9150db40fee1f2e17bf09d128c080f0bee9a3ac0c8bda9dbd0467e11a144c0f8",
}


@pytest.mark.parametrize("name", TEMPLATE_PINNED)
def test_template_fixture_is_the_verbatim_copy(name: str) -> None:
    import hashlib

    assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == TEMPLATE_PINNED[name]


def test_publishing_needs_no_node(docs: Docs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ts.NODE_OVERRIDE, str(tmp_path / "no-node-here"))
    with pytest.raises(ts.NodeLocatorError):
        ts.locate_node()
    gh = github(docs)
    assert ts.publish(docs.first, host=host(gh), name="dog-licensing", title="T")["written"] is True
    assert ts.publish_attestation(docs.withdrawal, host=host(gh), name="dog-licensing")["written"] is True


def test_the_first_publish_to_a_copy_in_its_starting_state(docs: Docs) -> None:
    """A publish-mode copy starts with ``"records": []`` and no ``records/`` directory (the template's
    README, setup step 5, at P1's 09fb6a5): the first publish appends the first entry, and the tree
    on ``base_tree`` creates ``records/<name>.signed.json``."""
    empty = template_manifest()
    empty["records"] = []
    files = {"host.json": dumps(empty), "host-policy.json": dumps(template_policy(docs.signer))}
    gh = FakeGitHub(files, token=TOKEN)
    assert not any(path.startswith("records/") for path in gh.files_at())
    start = gh.head
    receipt = ts.publish(docs.first, host=host(gh), notebook="dog-licensing.ipynb", title="Dog licensing")
    assert gh.requests == paths(gh, start) + writes(gh, blobs=2)
    name = receipt["name"]
    assert gh.json_at("host.json")["records"] == [
        {
            "name": name,
            "signed": f"records/{name}.signed.json",
            "attestations": [],
            "title": "Dog licensing",
            "extensions": {"role": "notebook"},
        }
    ]
    assert json.loads(gh.files_at()[f"records/{name}.signed.json"]) == docs.first
    tree_body = next(b for (m, p), b in zip(gh.requests, gh.bodies, strict=True) if p.endswith("/git/trees"))
    assert {item["path"] for item in tree_body["tree"]} == {f"records/{name}.signed.json", "host.json"}
