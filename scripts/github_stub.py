"""An in-memory stand-in for the GitHub REST API calls ``typedstandards.publish`` makes, served
through ``httpx.MockTransport``. No network, no file, no digest.

It models one repository: a branch head, commits holding whole file maps, blobs, trees, the
contents API's raw read, and a fast-forward-only ``PATCH git/refs/heads/<branch>``. Every request
is recorded as ``(method, path)`` in ``requests``. A request whose ``Authorization`` is not
``Bearer <token>`` answers 401. Object ids are counters, not hashes.

Shared by ``tests/test_publish.py``, ``scripts/smoke_wheel.py`` and the test of
``scripts/smoke_publish.py``, after the stub of ``spike/test/stub-api.mjs`` in the measured
reference client.
"""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

import httpx

API = "https://api.github.com"

#: host-policy.json's `display` with `notebook` in the active rule, as P1 changes the template's.
TEMPLATE_DISPLAY = [
    {
        "$comment": "An active note is shown as current.",
        "status": "active",
        "extensions": {"role": ["note", "notebook"]},
        "as": "current",
    },
    {"$comment": "A withdrawn record stays listed, marked withdrawn.", "status": "withdrawn", "as": "withdrawn"},
]


def manifest(origin: str = "https://publish.example.org", records: list[dict[str, Any]] | None = None) -> dict:
    """A host.json shaped like the template's, with its own origin and records."""
    return {
        "$comment": "The host manifest.",
        "origin": origin,
        "visibility": "public",
        "registry": {"$comment": "This host's statement about its key."},
        "index": {"$comment": "The records this host serves."},
        "records": records if records is not None else [],
    }


def policy(signer: str, display: list[dict[str, Any]] | None = None, **extra: Any) -> dict:
    """A host-policy.json shaped like the template's, naming ``signer``."""
    return {
        "$comment": "The display policy.",
        "signer": signer,
        "type": "content/analysis/v1",
        "display": display if display is not None else copy.deepcopy(TEMPLATE_DISPLAY),
        "unmatched": "refuse",
        **extra,
    }


def dumps(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


class FakeGitHub:
    """One repository's API. ``files`` maps a path to its bytes on the branch's head commit."""

    def __init__(
        self,
        files: dict[str, bytes],
        *,
        token: str,
        repository: str = "example-owner/example-host",
        branch: str = "main",
    ) -> None:
        self.repository = repository
        self.branch = branch
        self.token = token
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[Any] = []
        self._count = 0
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, bytes]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        first = self._id("c")
        self.trees[self._id("t")] = dict(files)
        self.commits[first] = {"tree": list(self.trees)[-1], "parents": [], "message": "initial"}
        self.head = first
        #: Before each of the next N ref updates, another writer's commit lands on the branch.
        self.concurrent_writes = 0
        #: Statuses to answer the next ref updates with after applying them (a write that landed).
        self.landed_but_failed: list[int] = []
        #: Called with each request before it is answered; may return a response to send instead.
        self.hook: Callable[[httpx.Request], httpx.Response | None] | None = None

    # --- state -------------------------------------------------------------------------------

    def _id(self, kind: str) -> str:
        """A fresh 40-hex object id (a counter; ``kind`` is for the reader)."""
        self._count += 1
        return f"{self._count:040x}"

    def files_at(self, commit: str | None = None) -> dict[str, bytes]:
        return self.trees[self.commits[commit or self.head]["tree"]]

    def json_at(self, path: str, commit: str | None = None) -> Any:
        return json.loads(self.files_at(commit)[path])

    def writes(self) -> list[tuple[str, str]]:
        return [r for r in self.requests if r[0] not in {"GET", "HEAD"}]

    def other_writer_commits(self) -> None:
        """A concurrent writer's commit: an unrelated file added on the branch."""
        files = dict(self.files_at())
        files[f"other/{self._count}.txt"] = b"another writer\n"
        tree = self._id("t")
        self.trees[tree] = files
        commit = self._id("c")
        self.commits[commit] = {"tree": tree, "parents": [self.head], "message": "another writer"}
        self.head = commit

    # --- the API -----------------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        body = json.loads(request.content) if request.content else None
        self.bodies.append(body)
        if self.hook is not None:
            answer = self.hook(request)
            if answer is not None:
                return answer
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        repo = f"/repos/{self.repository}"
        if not path.startswith(repo + "/"):
            return httpx.Response(404, json={"message": "Not Found"})
        rest = path[len(repo) :]
        method = request.method

        if method == "GET" and rest == f"/git/ref/heads/{self.branch}":
            return httpx.Response(200, json={"ref": f"refs/heads/{self.branch}", "object": {"sha": self.head}})
        if method == "GET" and rest.startswith("/git/commits/"):
            commit = self.commits.get(rest.rsplit("/", 1)[1])
            if commit is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"tree": {"sha": commit["tree"]}})
        if method == "GET" and rest.startswith("/contents/"):
            ref = request.url.params.get("ref", self.head)
            commit = self.commits.get(ref)
            content = None if commit is None else self.trees[commit["tree"]].get(unquote(rest[len("/contents/") :]))
            if content is None:
                return httpx.Response(404, json={"message": "Not Found"})
            if "raw" in request.headers.get("accept", ""):
                return httpx.Response(200, content=content)
            encoded = base64.b64encode(content).decode()
            return httpx.Response(200, json={"encoding": "base64", "content": encoded})
        if method == "POST" and rest == "/git/blobs":
            sha = self._id("b")
            self.blobs[sha] = base64.b64decode(body["content"])
            return httpx.Response(201, json={"sha": sha})
        if method == "POST" and rest == "/git/trees":
            base = self.trees.get(body.get("base_tree"))
            if base is None:
                return httpx.Response(422, json={"message": "base_tree not found"})
            files = dict(base)
            for item in body["tree"]:
                files[item["path"]] = self.blobs[item["sha"]]
            sha = self._id("t")
            self.trees[sha] = files
            return httpx.Response(201, json={"sha": sha})
        if method == "POST" and rest == "/git/commits":
            sha = self._id("c")
            self.commits[sha] = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}
            return httpx.Response(201, json={"sha": sha, "verification": {"verified": False, "reason": "unsigned"}})
        if method == "PATCH" and rest == f"/git/refs/heads/{self.branch}":
            if self.concurrent_writes > 0:
                self.concurrent_writes -= 1
                self.other_writer_commits()
            commit = self.commits.get(body["sha"])
            if commit is None or body.get("force") or commit["parents"] != [self.head]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.head = body["sha"]
            if self.landed_but_failed:
                return httpx.Response(self.landed_but_failed.pop(0), json={"message": "Server Error"})
            return httpx.Response(200, json={"object": {"sha": self.head}})
        return httpx.Response(404, json={"message": f"stub: no route for {method} {path}"})
