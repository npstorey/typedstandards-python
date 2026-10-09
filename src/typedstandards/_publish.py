"""``publish`` and ``publish_attestation``: write a signed record, or an attestation on one, to a
GitHub Pages host made from the host template's publish mode, in one commit.

The host's repository holds the template's inputs: ``host.json`` (the manifest host-core builds
from) and ``host-policy.json`` (the display policy). A publish reads both at the branch head,
checks the call against them, and writes the new files and the edited ``host.json`` through the
Git Data API: a blob per file, a tree on the head's tree, a commit whose parent is the head, and a
fast-forward of the branch. The host's workflow builds and deploys the site from that commit;
``publish`` does not wait for it.

What it does not do, by the package's rules: it computes no hash (a blob's id comes back from
``POST git/blobs``; ``envelopeHash`` and the signer are read from what ``sign`` printed), it never
runs the CLI, and it reads no signing seed. It reads one environment variable of its own, the
token's, sends the token only as the ``Authorization`` header of a client it builds and closes,
and never writes it to a file, a log record, a message or a return value.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import quote, urlsplit

from ._badge import verify_href
from .errors import PublishError, PublishRefusedError

if TYPE_CHECKING:  # httpx is imported inside the calls, so importing the package does not load it
    import httpx

#: The environment variable the token is read from when no ``token=`` is given.
TOKEN_VARIABLE = "TYPEDSTANDARDS_GITHUB_TOKEN"

#: A fine-grained personal access token's prefix.
FINE_GRAINED_PREFIX = "github_pat_"

_log = logging.getLogger("typedstandards")

_REPOSITORY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
_NAME_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

#: Path segments the verifier reads as a record page's URL anywhere in a bundle's path
#: (``apps/web/src/lib/verify-flow.ts:300,302,309`` in typedstandards).
_RECORD_PAGE_SEGMENTS = frozenset({"records", "evidence"})

#: The claim-to-claim sub-types a bundle does not carry (host-core ``records.ts``).
_CLAIM_TO_CLAIM = frozenset({"attestation/corroborates/v1", "attestation/contradicts/v1", "attestation/endorses/v1"})
_REVISES = "attestation/revises/v1"

#: Where the inputs a publish writes go, relative to host.json: the template keeps its signed
#: record under ``records/`` (``records/first-note.signed.json``), which is not served.
_INPUT_DIRECTORY = "records"


# --- the host --------------------------------------------------------------------------------


class _Token:
    """A token held for later, whose ``repr`` and ``str`` do not show it."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def __repr__(self) -> str:
        return "<token withheld>"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("a token is not pickled")

    def reveal(self) -> str:
        return self._value


class GitHubPagesHost:
    """A GitHub repository whose Pages site the host template's publish-mode workflow builds
    from ``host.json`` on ``branch``.

    ``repository`` is ``owner/name``. The token is ``token=``, else the environment variable
    ``TYPEDSTANDARDS_GITHUB_TOKEN`` read when a publish runs: a fine-grained personal access token
    for this one repository, with Contents read and write. Its ``repr`` names the repository and
    the branch only. ``client`` (used as given, not closed) or ``transport`` (for a client each
    call builds and closes), ``api_url`` and ``timeout`` are for tests and for callers with their
    own HTTP settings; redirects are never followed. The client a call builds ignores proxy and
    certificate environment variables; pass ``client=`` for those.
    """

    __slots__ = ("repository", "branch", "api_url", "timeout", "_token", "_client", "_transport")

    def __init__(
        self,
        repository: str,
        *,
        branch: str = "main",
        token: str | None = None,
        api_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not isinstance(repository, str) or not _REPOSITORY.match(repository):
            raise ValueError(f"repository must be owner/name, as in https://github.com/owner/name: {repository!r}")
        if not isinstance(branch, str) or not _BRANCH.match(branch) or ".." in branch:
            raise ValueError(f"branch must be a branch name: {branch!r}")
        if not isinstance(api_url, str) or not api_url.startswith("https://") or api_url.endswith("/"):
            raise ValueError("api_url must be an https:// URL with no trailing /")
        if token is not None and not isinstance(token, str):
            raise TypeError("token must be a string")
        self.repository = repository
        self.branch = branch
        self.api_url = api_url
        self.timeout = timeout
        self._token = _Token(token) if token is not None else None
        self._client = client
        self._transport = transport

    def __repr__(self) -> str:
        return f"GitHubPagesHost({self.repository!r}, branch={self.branch!r})"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("a GitHubPagesHost is not pickled: it may hold a token")

    def _resolve_token(self) -> str:
        """The token, checked before any request. A refusal holds no part of the value: not in its
        message, and not as a local of any frame its traceback shows (a verbose notebook
        traceback prints frames' locals)."""
        value = self._token.reveal() if self._token is not None else os.environ.get(TOKEN_VARIABLE)
        problem = _token_problem(value, "token=" if self._token is not None else TOKEN_VARIABLE)
        if problem is not None:
            del value
            _refuse(problem)
        return value  # type: ignore[return-value]  # _token_problem refuses None and ""


def _token_problem(value: str | None, source: str) -> str | None:
    """Why ``value`` is not a usable token, in words that never quote it; ``None`` when it is."""
    if not value:
        return (
            f"no GitHub token: pass token= or set {TOKEN_VARIABLE} (a fine-grained personal access token "
            "for this one repository, with Contents read and write)"
        )
    if "op://" in value:
        return f"{source} holds an op:// secret reference: the secret store did not resolve it"
    if re.search(r"[\s\"']", value):
        return f"{source} holds whitespace or a quote: pass the token's characters only"
    if not value.startswith(FINE_GRAINED_PREFIX) or value == FINE_GRAINED_PREFIX:
        return (
            f"{source} is not a fine-grained personal access token (one starts {FINE_GRAINED_PREFIX}): "
            "make one for this repository alone, with Contents read and write"
        )
    return None


def _refuse(message: str) -> NoReturn:
    raise PublishRefusedError(message)


# --- the API -----------------------------------------------------------------------------------


class _Api:
    """GitHub's REST API for one repository. The token is in the client's headers (or, for a
    given client, each request's) and nowhere else; what is logged is a method, a path and a
    status."""

    def __init__(self, host: GitHubPagesHost) -> None:
        import httpx

        self._httpx = httpx
        self.host = host
        self.base = f"{host.api_url}/repos/{host.repository}"
        self._own = host._client is None
        # The headers are built inside each call below, so no frame holds them as a local.
        if host._client is None:
            # trust_env=False: building the client does not iterate the environment (which holds the
            # signing seed) for proxy settings, and reads no .netrc. A caller who needs a proxy or a
            # certificate bundle passes client=.
            self._http = httpx.Client(
                headers=_headers(host),
                transport=host._transport,
                timeout=host.timeout,
                follow_redirects=False,
                trust_env=False,
            )
            self._headers: dict[str, str] = {}
        else:
            self._http = host._client
            self._headers = _headers(host)

    def close(self) -> None:
        if self._own:
            self._http.close()

    def _request_headers(self, accept: str | None) -> dict[str, str]:
        return {**self._headers, **({"Accept": accept} if accept is not None else {})}

    def _send(self, method: str, path: str, body: Any = None, *, accept: str | None = None) -> httpx.Response:
        try:
            response = self._http.request(
                method, self.base + path, json=body, headers=self._request_headers(accept), follow_redirects=False
            )
        except self._httpx.TransportError as error:
            _log.info("publish: %s %s -> no response (%s)", method, path, type(error).__name__)
            raise _NoResponse(f"{method} {path}: no response ({type(error).__name__})") from None
        _log.info("publish: %s %s -> %s", method, path, response.status_code)
        return response

    @staticmethod
    def _fail(method: str, path: str, response: httpx.Response) -> NoReturn:
        try:
            message = str(response.json().get("message", ""))[:200]
        except (ValueError, AttributeError):
            message = ""
        raise _ApiError(
            response.status_code, f"{method} {path} answered {response.status_code}: {message or '(no message)'}"
        )

    def get_json(self, path: str) -> Any:
        response = self._send("GET", path)
        if response.status_code != 200:
            self._fail("GET", path, response)
        return response.json()

    def read(self, path: str, ref: str) -> bytes | None:
        """A file's bytes at ``ref`` (the contents API's raw media type), or ``None`` for a 404."""
        at = quote(path, safe="/")
        response = self._send("GET", f"/contents/{at}?ref={ref}", accept="application/vnd.github.raw+json")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._fail("GET", f"/contents/{at}", response)
        return response.content

    def write(self, method: str, path: str, body: Any, expect: int) -> Any:
        """A Git Data API write: ``POST git/blobs|trees|commits`` or ``PATCH git/refs/heads/…``."""
        if method not in {"POST", "PATCH"} or not path.startswith("/git/"):
            raise AssertionError(f"publish writes through the Git Data API only, not {method} {path}")
        response = self._send(method, path, body)
        if response.status_code != expect:
            self._fail(method, path, response)
        return response.json()

    def head(self) -> str:
        sha = self.get_json(f"/git/ref/heads/{self.host.branch}").get("object", {}).get("sha")
        return _object_id(sha, f"the head of {self.host.branch}")


def _headers(host: GitHubPagesHost) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {host._resolve_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "typedstandards-python",
    }


class _ApiError(PublishError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _NoResponse(PublishError):
    pass


def _object_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _OBJECT_ID.match(value):
        raise PublishError(f"GitHub's answer for {what} carries no object id")
    return value


# --- JSON as host-core reads it ----------------------------------------------------------------


def _no_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not JSON")


def _parse_host_json(content: bytes) -> Any:
    """Parse bytes as host-core's ``parseJsonFile`` does (``json.ts:31-41``): strict UTF-8, with a
    leading byte-order mark dropped as ``TextDecoder`` drops it, and ``JSON.parse``, which has no
    ``NaN`` or ``Infinity``. Raises ``ValueError`` where host-core throws."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("is not UTF-8") from error
    return json.loads(text.removeprefix("\ufeff"), parse_constant=_no_constant)


# --- the host's files, read at the head ----------------------------------------------------------


@dataclass
class _State:
    head: str
    tree: str
    manifest: dict[str, Any]
    policy: dict[str, Any]
    api: _Api
    signed_cache: dict[str, dict[str, Any] | None] = field(default_factory=dict)

    def entry(self, name: str) -> dict[str, Any] | None:
        return next((e for e in self.manifest["records"] if e.get("name") == name), None)

    def signed_of(self, entry: Mapping[str, Any]) -> dict[str, Any] | None:
        """What the entry's ``signed`` file holds at the head, parsed, or ``None``."""
        path = entry.get("signed")
        if not isinstance(path, str):
            return None
        if path not in self.signed_cache:
            content = self.api.read(path, self.head)
            try:
                value = _parse_host_json(content) if content is not None else None
            except ValueError:
                value = None
            self.signed_cache[path] = value if isinstance(value, dict) else None
        return self.signed_cache[path]

    def hash_of(self, entry: Mapping[str, Any]) -> str | None:
        value = (self.signed_of(entry) or {}).get("envelopeHash")
        return value if isinstance(value, str) else None


def _read_state(api: _Api, head: str | None = None) -> _State:
    head = head or api.head()
    tree = _object_id(api.get_json(f"/git/commits/{head}").get("tree", {}).get("sha"), f"the tree of {head}")
    manifest = _read_json_file(api, "host.json", head)
    policy = _read_json_file(api, "host-policy.json", head)
    if not isinstance(manifest.get("records"), list) or not all(isinstance(e, dict) for e in manifest["records"]):
        _refuse("host.json has no records list of objects: it is not the manifest publish edits")
    origin = manifest.get("origin")
    if not isinstance(origin, str) or not origin.startswith("https://") or origin.endswith("/"):
        _refuse("host.json's origin is not an https:// origin with no trailing /")
    return _State(head, tree, manifest, policy, api)


def _read_json_file(api: _Api, path: str, head: str) -> dict[str, Any]:
    content = api.read(path, head)
    if content is None:
        _refuse(f"{path} is not on {api.host.branch}: publish writes to a host made from the host template")
    try:
        value = _parse_host_json(content)
    except ValueError:
        _refuse(f"{path} on {api.host.branch} is not JSON")
    if not isinstance(value, dict):
        _refuse(f"{path} on {api.host.branch} is not a JSON object")
    return value


def _strings(value: Any) -> list[str] | None:
    """A policy field that is a string or a list of strings, as a list; ``None`` when absent."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _check_signer(policy: Mapping[str, Any], signer: str, what: str) -> None:
    signers = _strings(policy.get("signer"))
    if not signers:
        _refuse("host-policy.json names no signer: publish compares the record's signer with it")
    if signer not in signers:
        _refuse(
            f"{what} is signed by {signer}, not by the signer host-policy.json names ({', '.join(signers)}): "
            "a host serves one signer's records"
        )


def _check_admitted(policy: Mapping[str, Any], *, signer: str, type_: str, role: str) -> None:
    """G0-3: an ``active`` record with this signer, type and role must match a display rule,
    as host-core's ``displayOf`` reads the policy, or every later deploy would fail."""
    types = _strings(policy.get("type"))
    if types is not None and type_ not in types:
        _refuse(f"the record's type {type_} is not one host-policy.json names ({', '.join(types)})")
    admitted: list[Any] = []
    for rule in policy.get("display") or []:
        if not isinstance(rule, dict) or "active" not in (_strings(rule.get("status")) or []):
            continue
        if (s := _strings(rule.get("signer"))) is not None and signer not in s:
            continue
        if (t := _strings(rule.get("type"))) is not None and type_ not in t:
            continue
        extensions = rule.get("extensions") or {}
        if not isinstance(extensions, dict) or set(extensions) - {"role"}:
            continue
        roles = extensions.get("role")
        if roles is None or (isinstance(roles, list) and role in roles):
            return
        admitted += roles if isinstance(roles, list) else []
    known = ", ".join(str(r) for r in admitted) or "none"
    _refuse(f"no active rule of host-policy.json admits the role {role} (roles active rules admit: {known})")


def _displayed(policy: Mapping[str, Any], *, status: str, signer: str, type_: str, extensions: Mapping) -> bool:
    """Whether host-core's ``displayOf`` (``display.ts:118-145``) shows a record with this status,
    signer, type and index ``extensions`` under the policy, as the template's display step runs it."""
    for key, value in (("signer", signer), ("type", type_)):
        named = _strings(policy.get(key))
        if named is not None and value not in named:
            return False
    for rule in policy.get("display") or []:
        if not isinstance(rule, dict) or status not in (_strings(rule.get("status")) or []):
            continue
        if any(
            (named := _strings(rule.get(k))) is not None and v not in named
            for k, v in (("signer", signer), ("type", type_))
        ):
            continue
        admitted = rule.get("extensions") or {}
        if isinstance(admitted, dict) and all(
            k in extensions and isinstance(values, list) and extensions[k] in values for k, values in admitted.items()
        ):
            return True
    return False


#: The status a lifecycle node moves its record to, as verify-core reads the latest node
#: (``lifecycle.ts:192-198``); a ``revises`` node moves none.
_STATUS_AFTER = {
    "attestation/withdraws/v1": "withdrawn",
    "attestation/supersedes/v1": "superseded",
    "attestation/reinstates/v1": "active",
}

_MANIFEST_ORIGIN = re.compile(r"^https://[^/?#\s]+(/[^?#\s]*[^/?#\s])?$")
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _relative(path: Any) -> bool:
    return isinstance(path, str) and path != "" and not path.startswith("/") and not _WINDOWS_PATH.match(path)


def _manifest_problem(m: Any) -> str | None:
    """host-core's ``parseManifest`` (``manifest.ts:41-95``): why it would refuse ``m``, or ``None``."""
    if not isinstance(m, dict):
        return "host.json must be a JSON object"
    extra = sorted(set(m) - {"$comment", "origin", "visibility", "registry", "index", "records"})
    missing = sorted({"origin", "registry", "index", "records"} - set(m))
    if extra or missing:
        return f"host.json: {', '.join(extra)} not defined" if extra else f"host.json is missing {', '.join(missing)}"
    if not isinstance(m["origin"], str) or not _MANIFEST_ORIGIN.match(m["origin"]):
        return "host.json: origin must be an https:// origin with no trailing /, query or fragment"
    if not isinstance(m.get("visibility"), str) or not m["visibility"]:
        return "host.json: visibility is required"
    for key in ("registry", "index"):
        value = m[key]
        if key == "registry" and value is None:
            continue
        if not isinstance(value, dict) or set(value) - {"$comment"}:
            return f"host.json: {key} must be an object holding at most $comment" + (
                " or null" if key == "registry" else ""
            )
        if "$comment" in value and not isinstance(value["$comment"], str):
            return f"host.json: {key}.$comment must be a string"
    records = m["records"]
    if not isinstance(records, list) or not records:
        return "host.json: records must be a non-empty array"
    seen: set[str] = set()
    for i, r in enumerate(records):
        at = f"host.json: records[{i}]"
        if not isinstance(r, dict):
            return f"{at} must be an object"
        extra = sorted(set(r) - {"$comment", "name", "signed", "attestations", "title", "extensions"})
        missing = sorted({"name", "signed", "attestations", "title"} - set(r))
        if extra or missing:
            return f"{at}: {', '.join(extra)} not defined" if extra else f"{at} is missing {', '.join(missing)}"
        name = r["name"]
        if not isinstance(name, str) or not all(
            _NAME_SEGMENT.match(x) and x not in {".", ".."} for x in name.split("/")
        ):
            return f"{at}.name fails the record-name rule"
        if name in seen:
            return f"{at}.name: {name} is listed twice"
        seen.add(name)
        if not _relative(r["signed"]):
            return f"{at}.signed must be a path relative to host.json"
        if not isinstance(r["attestations"], list) or not all(_relative(a) for a in r["attestations"]):
            return f"{at}.attestations must be an array of paths relative to host.json"
        if not isinstance(r["title"], str) or not r["title"]:
            return f"{at}.title must be a non-empty string"
        if "extensions" in r and not isinstance(r["extensions"], dict):
            return f"{at}.extensions must be an object"
    return None


def _check_manifest(manifest: Any) -> None:
    if (problem := _manifest_problem(manifest)) is not None:
        _refuse(f"the host.json publish would write fails host-core's manifest rule: {problem}")


def _check_listed(state: _State) -> None:
    """Read every listed record's signed file (once: ``signed_cache``) and refuse when host-core's
    build already fails on one: unreadable, not what sign prints, or, under a registry, a signer,
    display name or key unlike the first record's (``build.ts:49-66``, ``:93-97``)."""
    first: dict[str, Any] | None = None
    for entry in state.manifest["records"]:
        document = state.signed_of(entry)
        label = entry.get("name")
        if document is None:
            _refuse(f"the host's build already fails on {label}: its signed file cannot be read as JSON")
        if (problem := _signed_problem(document)) is not None:
            _refuse(f"the host's build already fails on {label}: {problem}")
        if state.manifest.get("registry") is not None:
            if first is None:
                first = document
            elif (problem := _one_signer_problem(document, first)) is not None:
                _refuse(f"the host's build already fails on {label}: {problem}")


def _one_signer_problem(document: Mapping[str, Any], first: Mapping[str, Any]) -> str | None:
    """host-core's registry rule (``build.ts:90-98``): one signer identifier, binding tier, display
    name and key for every record under a registry, and a signature ``kid`` that is the signer."""
    a, b = _signer_of(document), _signer_of(first)
    if any(a.get(k) != b.get(k) for k in ("identifier", "bindingTier", "displayName")) or (
        document["signature"].get("publicKey") != first["signature"].get("publicKey")
    ):
        return (
            f"its signer ({a.get('identifier')}, {a.get('bindingTier')}, {a.get('displayName')!r}) or key differs from "
            f"the first record's ({b.get('identifier')}, {b.get('bindingTier')}, {b.get('displayName')!r}); a host "
            "under a registry serves one signer"
        )
    kid = document["signature"].get("kid")
    if kid is not None and kid != a.get("identifier"):
        return f"its signature's kid {kid} is not the signer's identifier {a.get('identifier')}"
    return None


def _check_registry_rules(state: _State, document: Mapping[str, Any]) -> None:
    """The rules host-core's build applies to a new record by the host's registry: under one, the
    first listed record's signer and key (or, for a host's first record, the record's own kid);
    with ``registry: null``, produce-core's view takes only a self-certifying signer, a
    pseudonymous ``did:key`` (``build.ts:147-148``, ``commitment.ts:200-215``)."""
    signer = _signer_of(document)
    if state.manifest.get("registry") is None:
        if signer.get("bindingTier") != "pseudonymous" or not str(signer.get("identifier", "")).startswith("did:key:"):
            _refuse(
                "host.json's registry is null, under which host-core builds a view only for a pseudonymous did:key "
                f"signer; this record's is {signer.get('identifier')} at {signer.get('bindingTier')}"
            )
        return
    records = state.manifest["records"]
    first = state.signed_of(records[0]) if records else None
    if (problem := _one_signer_problem(document, first if first is not None else document)) is not None:
        _refuse(f"the record: {problem}")


def _check_path_unnamed(manifest: Mapping[str, Any], path: str) -> None:
    """A file another entry lists is not overwritten: the build would read this record's bytes
    under that entry (``build.ts:65-66``, ``:70-71``)."""
    for entry in manifest["records"]:
        if entry.get("signed") == path or path in (entry.get("attestations") or []):
            _refuse(f"host.json's entry {entry.get('name')} already names {path}: publish does not overwrite it")


# --- the call's own checks, before any request --------------------------------------------------


def _load(value: Mapping[str, Any] | str | os.PathLike[str], what: str) -> tuple[Any, bytes | None]:
    """A document given as a mapping (written as JSON) or a path (written as its bytes)."""
    if isinstance(value, Mapping):
        return value, None
    if isinstance(value, (str, os.PathLike)):
        content = Path(value).read_bytes()
        try:
            return _parse_host_json(content), content
        except ValueError as error:
            _refuse(f"{os.fspath(value)} {error}, as host-core reads a file (UTF-8, JSON.parse): {what}")
    return value, None


def _serialize(value: Any) -> bytes:
    """JSON with two-space indentation and a newline. A value JSON.parse would refuse (NaN,
    Infinity) is refused."""
    try:
        return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except ValueError as error:
        _refuse(f"a document holds a value JSON cannot carry ({error}): host-core could not read it")


def _signature_problem(value: Any) -> str | None:
    """host-core's ``checkSignature`` (``records.ts:43-50``)."""
    if not isinstance(value, Mapping) or not isinstance(value.get("signature"), str):
        return "its signature must be an object with a signature and a publicKey string"
    if not isinstance(value.get("publicKey"), str):
        return "its signature must be an object with a signature and a publicKey string"
    for key in ("algorithm", "kid"):
        if key in value and not isinstance(value[key], str):
            return f"its signature's {key} must be a string"
    return None


def _signed_problem(value: Any) -> str | None:
    """Why host-core's build would refuse a signed file: ``checkSignedDocument``
    (``records.ts:54-66``), then the package's ``metadata.createdAt`` and ``signer.identifier``
    (``build.ts:61-64``). ``None`` when it would not."""
    if not isinstance(value, Mapping) or set(value) != {"package", "envelopeHash", "signature"}:
        return "it is not what sign prints: {package, envelopeHash, signature}"
    if not isinstance(value["package"], Mapping):
        return "its package is not an object"
    if not isinstance(value["envelopeHash"], str) or not _HEX_64.match(value["envelopeHash"]):
        return "its envelopeHash is not 64 lowercase hex characters"
    if (problem := _signature_problem(value["signature"])) is not None:
        return problem
    metadata = value["package"].get("metadata")
    created_at = metadata.get("createdAt") if isinstance(metadata, Mapping) else None
    if not isinstance(created_at, str) or not created_at:
        return "its package has no metadata.createdAt, which the index states"
    if not _signer_of(value).get("identifier"):
        return "its package has no signer.identifier, which the index states"
    return None


def _signer_of(document: Mapping[str, Any]) -> dict[str, Any]:
    signer = document["package"].get("signer") if isinstance(document.get("package"), Mapping) else None
    return dict(signer) if isinstance(signer, Mapping) else {}


def _check_signed(value: Any) -> tuple[str, str, str, str]:
    """``(envelopeHash, signer identifier, type, createdAt)`` from what ``sign`` printed."""
    if (problem := _signed_problem(value)) is not None:
        _refuse(f"publish takes what sign prints, as host-core's build reads it: {problem}")
    package = value["package"]
    envelope_hash = value["envelopeHash"]
    output = package.get("output")
    if isinstance(output, Mapping):
        _refuse(
            "the record's output is a BlobRef (signed by reference, with output_url=): a host made from the "
            "template serves the signed file only, so publish takes a record whose output is inline "
            "(sign with output_file= and no output_url=)"
        )
    signer = (package.get("signer") or {}).get("identifier") if isinstance(package.get("signer"), Mapping) else None
    if not isinstance(signer, str) or not signer:
        _refuse("the record's package names no signer.identifier")
    type_ = package.get("type")
    created_at = (
        (package.get("metadata") or {}).get("createdAt") if isinstance(package.get("metadata"), Mapping) else None
    )
    if not isinstance(type_, str) or not isinstance(created_at, str):
        _refuse("the record's package has no type or metadata.createdAt: publish takes what sign prints")
    return envelope_hash, signer, type_, created_at


def _check_node(value: Any, what: str) -> tuple[str, str, str, dict[str, Any]]:
    """``(nodeId, type, signer identifier, node)`` from what ``withdraw`` or ``attest`` printed."""
    if not isinstance(value, Mapping) or set(value) != {"node", "nodeId", "signature"}:
        _refuse(f"{what} takes what withdraw or attest prints: {{node, nodeId, signature}}")
    node, node_id = value["node"], value["nodeId"]
    if not isinstance(node, Mapping) or not isinstance(node_id, str) or not _HEX_64.match(node_id):
        _refuse(f"{what}: node must be an object and nodeId 64 lowercase hex characters")
    type_ = node.get("type")
    if not isinstance(type_, str) or not type_.startswith("attestation/"):
        _refuse(f"{what}: node.type is not an attestation type")
    if type_ in _CLAIM_TO_CLAIM:
        _refuse(f"{what} is an {type_}, a claim-to-claim node: a bundle carries lifecycle attestations only")
    signer = node.get("signer", {}).get("identifier") if isinstance(node.get("signer"), Mapping) else None
    if not isinstance(signer, str):
        _refuse(f"{what}: node names no signer.identifier")
    if (problem := _signature_problem(value["signature"])) is not None:
        _refuse(f"{what}: {problem}")
    return node_id, type_, signer, dict(node)


def check_name(name: Any) -> str:
    """host-core's record-name rule, and no ``records`` or ``evidence`` segment."""
    if not isinstance(name, str) or not all(_NAME_SEGMENT.match(s) and s not in {".", ".."} for s in name.split("/")):
        _refuse(
            f"the name {name!r} must be /-separated segments of letters, digits, '.', '_' and '-', with no "
            "'.' or '..' segment (host-core's rule)"
        )
    if _RECORD_PAGE_SEGMENTS & set(name.split("/")):
        _refuse(
            f"the name {name} has a records or evidence segment, which the verifier reads as a record page's "
            "URL rather than a bundle's: choose another name"
        )
    return name


def default_name(notebook: str | os.PathLike[str], envelope_hash: str, created_at: str) -> str:
    """``<the notebook's stem>/<createdAt's date>-<the first eight hex of envelopeHash>``."""
    if not _DATE.match(created_at):
        _refuse("the record's metadata.createdAt does not start with a date")
    return f"{PurePath(os.fspath(notebook)).stem}/{created_at[:10]}-{envelope_hash[:8]}"


def _bundle_url(origin: str, name: str) -> str:
    url = f"{origin}/bundles/{name}.bundle.json"
    if _RECORD_PAGE_SEGMENTS & set(urlsplit(url).path.split("/")):
        _refuse(
            f"{url} has a records or evidence segment, which the verifier reads as a record page's URL: "
            "host.json's origin or the name must change"
        )
    return url


def _receipt(state: _State, name: str, commit: str | None) -> dict[str, Any]:
    origin = state.manifest["origin"]
    bundle_url = _bundle_url(origin, name)
    registry = state.manifest.get("registry")
    return {
        "name": name,
        "commit": commit,
        "bundle_url": bundle_url,
        "verify_url": verify_href(bundle_url),
        "registry_url": f"{origin}/.well-known/typed-publisher.json" if registry is not None else None,
        "written": commit is not None,
        "run": None,
    }


# --- the write ---------------------------------------------------------------------------------


@dataclass
class _Plan:
    """What one commit writes: the files (path to bytes), the manifest, the message, the name."""

    files: dict[str, bytes]
    manifest: dict[str, Any]
    message: str
    name: str


def _commit(api: _Api, plan_for: Callable[[_State], _Plan | dict[str, Any]]) -> dict[str, Any]:
    """Read the head, plan, write one commit, fast-forward the branch. On a ref update that did
    not answer 200, re-read the head first: a write that errored may have landed. If it did not,
    and the branch moved (not a fast forward) or no answer came, plan again from the new head
    once; a second failure is an error."""
    head: str | None = None
    for attempt in (1, 2):
        state = _read_state(api, head)
        plan = plan_for(state)
        if isinstance(plan, dict):
            return plan
        entries = []
        for path, content in [*plan.files.items(), ("host.json", _serialize(plan.manifest))]:
            blob = api.write("POST", "/git/blobs", {"content": _b64(content), "encoding": "base64"}, 201)
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": _object_id(blob.get("sha"), path)})
        tree = api.write("POST", "/git/trees", {"base_tree": state.tree, "tree": entries}, 201)
        made = api.write(
            "POST",
            "/git/commits",
            {"message": plan.message, "tree": _object_id(tree.get("sha"), "the tree"), "parents": [state.head]},
            201,
        )
        commit = _object_id(made.get("sha"), "the commit")
        ref = f"/git/refs/heads/{api.host.branch}"
        try:
            api.write("PATCH", ref, {"sha": commit, "force": False}, 200)
            _log.info("publish: %s is %s on %s", plan.name, commit, api.host.branch)
            return _receipt(state, plan.name, commit)
        except (_ApiError, _NoResponse) as error:
            head = api.head()
            if head == commit:
                _log.info("publish: the ref update errored but landed: %s", commit)
                return _receipt(state, plan.name, commit)
            retry = isinstance(error, _NoResponse) or error.status == 422
            if not retry or attempt == 2:
                raise PublishError(
                    f"{error}; {api.host.branch} is at {head}, not the new commit {commit}"
                    + (" after one retry: not a fast forward twice" if retry else "")
                ) from None
            _log.info("publish: %s moved to %s; planning again from it", api.host.branch, head)
    raise AssertionError("unreachable")


def _b64(content: bytes) -> str:
    import base64

    return base64.b64encode(content).decode("ascii")


def _run(host: GitHubPagesHost, plan_for: Callable[[_State], _Plan | dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(host, GitHubPagesHost):
        raise TypeError("host must be a GitHubPagesHost")
    api = _Api(host)
    try:
        return _commit(api, plan_for)
    finally:
        api.close()


# --- publish ------------------------------------------------------------------------------------


def _node_path(record_name: str, type_: str, node_id: str) -> str:
    return f"{_INPUT_DIRECTORY}/{record_name}.{type_.split('/')[1]}-{node_id[:8]}.json"


def publish(
    signed: Mapping[str, Any] | str | os.PathLike[str],
    *,
    host: GitHubPagesHost,
    title: str,
    name: str | None = None,
    notebook: str | os.PathLike[str] | None = None,
    role: str = "notebook",
    revises: Mapping[str, Any] | str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Publish what :func:`sign` printed (or its path) to ``host`` in one commit.

    The record is listed in ``host.json`` under ``name``, or under the default name
    ``<stem>/<date>-<eight hex>`` from ``notebook`` (the file's stem), the date of the record's
    ``createdAt`` and the first eight hex of its ``envelopeHash``. Its file is written at
    ``records/<name>.signed.json``, its entry gets ``title`` and ``extensions.role``.

    A record whose ``envelopeHash`` any listed entry carries is not written again, under any name
    (``written: False``); the receipt names that entry. To find it, each call reads every listed
    record's signed file once. A name listed with another record is refused, unless ``revises=``
    is what :func:`attest` printed for an ``attestation/revises/v1`` from the listed record to this
    one: then the record is written under ``<name>-<its first eight hex>``, and the node on the
    listed record's entry, in the same commit. Under a name that is not listed, ``revises=`` goes
    on the entry of the listed record it targets.

    Refused before any write: a token that is not a fine-grained one, a name that fails
    host-core's rule or has a ``records`` or ``evidence`` segment, an empty title, a BlobRef
    output, a signer other than ``host-policy.json``'s, a role no active rule admits, a
    ``revises=`` whose type, ``successorNodeId`` or ``targetNodeId`` does not match, and what
    host-core's build would refuse once the commit lands.

    Returns ``{name, commit, bundle_url, verify_url, registry_url, written, run}``; ``run`` is
    ``None``: the host's workflow deploys the commit, and publish does not wait for it.
    """
    document, original = _load(signed, "publish takes what sign prints")
    envelope_hash, signer, type_, created_at = _check_signed(document)
    if name is not None and notebook is not None:
        raise TypeError("publish takes name= or notebook= (for the default name), not both")
    if name is None:
        if notebook is None:
            raise TypeError("publish takes name= or notebook= (whose stem starts the default name)")
        name = default_name(notebook, envelope_hash, created_at)
    name = check_name(name)
    if not isinstance(title, str) or not title.strip():
        _refuse("the title is empty: it becomes the view's subjectTitle")
    if not isinstance(role, str) or not role:
        _refuse("the role is empty")
    node: dict[str, Any] | None = None
    node_bytes: bytes | None = None
    if revises is not None:
        revises_document, revises_original = _load(revises, "revises= takes what attest prints")
        node_id, node_type, node_signer, node = _check_node(revises_document, "revises=")
        if node_type != _REVISES:
            _refuse(f"revises= is an {node_type}, not an {_REVISES}")
        if node.get("successorNodeId") != envelope_hash:
            _refuse("revises= names another successorNodeId than this record's envelopeHash")
        node_bytes = revises_original if revises_original is not None else _serialize(revises_document)
    content = original if original is not None else _serialize(document)
    host._resolve_token()  # refuse a token before any request

    def plan_for(state: _State) -> _Plan | dict[str, Any]:
        _bundle_url(state.manifest["origin"], name)
        # Every listed record's signed file, read once: host-core lists a hash once (build.ts:65-66).
        _check_listed(state)
        carried = next((e for e in state.manifest["records"] if state.hash_of(e) == envelope_hash), None)
        if carried is not None:
            return _receipt(state, carried["name"], None)
        _check_signer(state.policy, signer, "the record")
        if node is not None:
            _check_signer(state.policy, node_signer, "revises=")
        _check_admitted(state.policy, signer=signer, type_=type_, role=role)
        _check_registry_rules(state, document)
        record_name = name
        target: dict[str, Any] | None = None
        listed = state.entry(name)
        if listed is not None:
            listed_hash = state.hash_of(listed)
            if node is None:
                _refuse(
                    f"{name} is listed with another record (envelopeHash {listed_hash or 'unread'}): pass "
                    "revises= (what attest printed for attestation/revises/v1 from it to this record) or another name"
                )
            if node.get("targetNodeId") != listed_hash:
                _refuse(f"revises= targets {node.get('targetNodeId')}, not the record listed as {name}")
            target = listed
            record_name = check_name(f"{name}-{envelope_hash[:8]}")
            if state.entry(record_name) is not None:
                _refuse(f"{record_name}, the name a revision of {name} takes, is listed with another record")
            _bundle_url(state.manifest["origin"], record_name)
        elif node is not None:
            target = next(
                (e for e in reversed(state.manifest["records"]) if state.hash_of(e) == node.get("targetNodeId")),
                None,
            )
            if target is None:
                _refuse(f"revises= targets {node.get('targetNodeId')}, and no record this host lists has that hash")
        manifest = copy.deepcopy(state.manifest)
        signed_path = f"{_INPUT_DIRECTORY}/{record_name}.signed.json"
        _check_path_unnamed(manifest, signed_path)
        files = {signed_path: content}
        manifest["records"].append(
            {
                "name": record_name,
                "signed": signed_path,
                "attestations": [],
                "title": title,
                "extensions": {"role": role},
            }
        )
        message = f"Publish {record_name}"
        if target is not None and node is not None and node_bytes is not None:
            node_path = _node_path(target["name"], _REVISES, node_id)
            entry = next(e for e in manifest["records"] if e.get("name") == target["name"])
            if node_path not in entry.setdefault("attestations", []):  # a listed node file stays as it is
                _check_path_unnamed(manifest, node_path)
                entry["attestations"].append(node_path)
                files[node_path] = node_bytes
            message = f"Publish {record_name}, a revision of {target['name']}"
        _check_manifest(manifest)
        return _Plan(files, manifest, message, record_name)

    return _run(host, plan_for)


def publish_attestation(
    node: Mapping[str, Any] | str | os.PathLike[str], *, host: GitHubPagesHost, name: str
) -> dict[str, Any]:
    """Add what :func:`withdraw` or :func:`attest` printed (or its path) to the record listed as
    ``name``, in one commit: the node's file at ``records/<name>.<kind>-<eight hex>.json`` and its
    path in the entry's ``attestations``.

    Refused before any write: a token that is not a fine-grained one, a claim-to-claim node
    (``corroborates``, ``contradicts``), a name the host does not list, a node aimed at another
    record (its ``targetNodeId`` is not the listed record's ``envelopeHash``), a signer other
    than ``host-policy.json``'s, and a withdrawal or supersession that would leave the record in a
    status no policy rule displays. A node already listed on the entry is not written again
    (``written: False``). Returns the receipt :func:`publish` returns, for the record.
    """
    document, original = _load(node, "publish_attestation takes what withdraw or attest prints")
    node_id, type_, signer, body = _check_node(document, "the attestation")
    check_name(name)
    content = original if original is not None else _serialize(document)
    host._resolve_token()

    def plan_for(state: _State) -> _Plan | dict[str, Any]:
        _bundle_url(state.manifest["origin"], name)
        _check_signer(state.policy, signer, "the attestation")
        listed = state.entry(name)
        if listed is None:
            _refuse(f"host.json lists no record named {name}")
        listed_hash = state.hash_of(listed)
        if body.get("targetNodeId") != listed_hash:
            _refuse(f"the attestation's targetNodeId is not the envelopeHash of the record listed as {name}")
        path = _node_path(name, type_, node_id)
        if path in (listed.get("attestations") or []):
            existing = state.api.read(path, state.head)
            try:
                same = existing is not None and _parse_host_json(existing).get("nodeId") == node_id
            except (ValueError, AttributeError):
                same = False
            if same:
                return _receipt(state, name, None)
            _refuse(f"{path} is listed on {name} with another node")
        status = _STATUS_AFTER.get(type_)
        record = state.signed_of(listed) or {}
        if status is not None and not _displayed(
            state.policy,
            status=status,
            signer=str(_signer_of(record).get("identifier", "")) if record else "",
            type_=str((record.get("package") or {}).get("type") or "content/analysis/v1"),
            extensions=listed.get("extensions") or {},
        ):
            _refuse(
                f"no rule of host-policy.json displays {name} once it is {status}: the host's display step would "
                f"refuse it, and with it every later deploy. Add a rule for {status} records first"
            )
        manifest = copy.deepcopy(state.manifest)
        _check_path_unnamed(manifest, path)
        entry = next(e for e in manifest["records"] if e.get("name") == name)
        entry.setdefault("attestations", []).append(path)
        _check_manifest(manifest)
        return _Plan(
            {path: content}, manifest, f"Add the {type_.split('/')[1]} attestation {node_id[:8]} to {name}", name
        )

    return _run(host, plan_for)
