# typedstandards

Sign, withdraw, attest to, build views of and verify [Typed Standards](https://typedstandards.org)
records from Python. The package drives
[`@typedstandards/cli`](https://www.npmjs.com/package/@typedstandards/cli) 0.2.0 as a child
process. It holds no key, reads no signing seed, and computes none of the format's hashes: the CLI
does all of the format's work.

## Install

```sh
pip install typedstandards        # or: uv add typedstandards
```

The wheel carries the CLI and its dependencies (vendored at build time from this repository's
`package-lock.json`), so installing needs nothing from npm. Running needs Node.js: the wrapper and
the CLI need Node 20.19 or later, and a `@typedstandards/host-core` site build needs Node 22 or
later.

The wrapper looks for Node in this order:

1. `TYPEDSTANDARDS_NODE`, when set: the path (or name on `PATH`) of a Node binary;
2. `node` on `PATH`.

Only the calls that run the CLI need Node: `sign`, `withdraw`, `attest`, `view`, `verify`,
`cli_version()`, and `show` without a precomputed result. With no Node, or one older than 20.19.0,
each of those raises `typedstandards.NodeLocatorError`, whose message names the floor and
`TYPEDSTANDARDS_NODE`. `pin`, `badge_cell`, `comparison_cell`, `sidecar`, `show(record, result)`,
`publish` and `publish_attestation` run without Node.

Linux and macOS are tested. Windows is untested.

## The signing key

The CLI reads the signing seed (the standard base64 of a 32-byte Ed25519 seed) from one environment
variable, `TYPEDSTANDARDS_SIGNING_SEED_B64`, and from nowhere else. The wrapper never reads it: it
starts the CLI with the environment it inherited, and passes no environment of its own. Set the
variable from a secret store for the process that signs, for example:

```sh
op run --env-file=signing.env -- jupyter lab
```

where `signing.env` maps `TYPEDSTANDARDS_SIGNING_SEED_B64` to a secret reference. Make a new seed
with:

```sh
openssl rand -base64 32
```

Only `sign`, `withdraw` and `attest` need it; `view` and `verify` do not.

## Use

```python
import typedstandards as ts

signed = ts.sign(
    {
        "type": "content/analysis/v1",
        "producerProfile": "scripted-recomputation/example",
        "captureMethod": "script-run",
        "prompt": "Recompute the summary table.",
        "promptVisibility": "full_text",
        "queries": [],
        "dataSources": [],
        "cost": {"model": "none"},
        "skillMetadata": {},
        "trace": {},
        "signer": {"bindingTier": "pseudonymous", "displayName": "Example analyst"},
    },
    output_file="analysis.ipynb",
)  # signed inline under raw-bytes/v1

bundle = ts.view(signed, visibility="public", title="Example analysis")
result = ts.verify(bundle)  # {ok, nodeId, failures, checks, lifecycle}
```

Each function returns the CLI's stdout parsed as JSON. An input may be a mapping (written as JSON
to a temporary file the CLI reads) or the path of a JSON file.

| Function | CLI command | Returns |
|---|---|---|
| `sign(input, *, output_file=None, output_url=None, content_type=None)` | `sign` | `{package, envelopeHash, signature}` |
| `withdraw(input)` | `withdraw` | `{node, nodeId, signature}` |
| `attest(input)` | `attest` | `{node, nodeId, signature}` |
| `view(signed, *, visibility, attestations=(), trust_registry_url=None, package_url=None, title=None)` | `view` | the commitment view, package inline |
| `verify(input, *, blobs=(), full=True)` | `verify` (`--json` when `full`) | `{ok, nodeId, failures, checks, lifecycle}` |

The temporary files are removed before the function returns, whether the CLI succeeded or not. No
input reaches the CLI through a pipe, where CLI 0.2.0 fails on a document larger than a pipe buffer
holds. The CLI's
[README](https://github.com/npstorey/typedstandards/tree/main/packages/cli#readme) describes each
command's inputs. What the CLI prints on stderr when it succeeds (attention readings, such as an
offline `registry_unavailable`) is logged at INFO on the `typedstandards` logger.

`typedstandards.CLI_VERSION` is the version of the vendored CLI (`"0.2.0"`), and
`typedstandards.cli_version()` asks the vendored CLI for it.

### Errors

A non-zero exit raises a subclass of `typedstandards.CliError`, which carries `exit_code`, `stderr`
(the CLI's standard error) and `command`:

| Exit | Exception | Meaning |
|---|---|---|
| 1 | `VerificationError` | a record, or the CLI's own result, did not verify; for `verify`, `.document` is the `{ok: false, ...}` verdict |
| 2 | `UsageError` | an argument or an input is wrong |
| 3 | `SeedError` | the seed's variable is missing or malformed |
| 4 | `InternalError` | an internal error in the CLI |

### Verifying a served bundle

`@typedstandards/host-core` inlines a top-level `trustRegistry` in every bundle it serves under a
registry, and CLI 0.2.0's `verify` refuses that key
([typedstandards#136](https://github.com/npstorey/typedstandards/issues/136)). Until the wrapper
pins a CLI that accepts it, `verify` drops a bundle's top-level `trustRegistry` before the CLI
sees the bundle, and changes nothing else. A test pins that the CLI receives the same document
minus that one key.

## Notebook helpers

Five helpers arrange and render around the CLI. None of them computes one of the format's hashes,
reads the seed, or verifies anything itself.

```python
import io
import pandas as pd
import typedstandards as ts

# Before signing: pin each input, and add the reader's badge and the comparison cell.
content, entry = ts.pin("https://data.example.org/resource/abcd-1234.csv", licence="CC-BY-4.0")
frame = pd.read_csv(io.BytesIO(content))

ts.badge_cell(
    "https://records.example.org/bundles/analysis.bundle.json",
    capture_method="script-run",
    notebook="analysis.ipynb",
)
ts.comparison_cell(
    "analysis.ipynb",
    {"rows": 1204, "mean_fare": 13.75},
    recompute="recompute_key_metrics()",
    captured_at="2026-10-03T12:00:00Z",
)

# Sign (record is an envelope input like the one under Use), then serve and show.
signed = ts.sign({**record, "queries": [entry]}, output_file="analysis.ipynb")
bundle = ts.view(signed, visibility="public", title="Example analysis")
ts.sidecar(bundle, "analysis.ipynb")  # writes analysis.ipynb.record.yaml
ts.show(bundle)  # in Jupyter; ts.show(bundle, marimo=True) in Marimo
```

- **`pin(url, *, licence=None, dataset_id=None, portal_metadata=None, save=None, ...)`** fetches
  `url` once and returns `Pinned(content, entry)`: the response body, and a retrieval entry for
  the record's `queries[]` with `url`, `sha256` (of the body), `bytes`, `httpStatus` and
  `fetchedAt` (ISO 8601 UTC) under `arguments`. A URL shaped like an open-data portal resource
  (`…/resource/<id>[.ext]` or `…/api/views/<id>/rows.<ext>`, `<id>` being `xxxx-xxxx`) gets a
  second request to `<origin>/api/views/<id>`, and the entry gains the portal's `rowsUpdatedAt`
  (epoch seconds) and `datasetId`. A response that is not 2xx raises. `save=` writes the bytes
  to that path and the entry to `<path>.pin.json`. The SHA-256 is the one digest the package
  computes: a signed assertion in `queries[]` that no check recomputes.
- **`badge_cell(bundle_url, *, capture_method, notebook=None, host=None, marimo=False)`** writes
  the verifier badge, linked to `https://typedstandards.org/verify?url=<the bundle URL,
  percent-encoded>` as `@typedstandards/host-core` writes it, above a two-row table (the host and
  the capture method). With `notebook`, it is inserted as the notebook's first cell (id
  `typedstandards-badge` on nbformat 4.5). With `marimo=True`, it returns the source of a
  `mo.md(...)` cell to paste into the app. The cell is written before signing and is part of the
  signed bytes, so it names no hash and no time; a URL or value holding a 64-hex string, a date or
  a time is refused. The URL's host and port are not read as a time (`192.168.1.10:8080` is
  accepted).
- **`comparison_cell(notebook, values, *, recompute, captured_at)`** appends the comparison cell
  of spec §8.7.4 as the last cell (id `typedstandards-comparison`): the values as Python literals,
  `current = <recompute>`, and a loop that prints each delta. Values are `None`, `bool`, `int`,
  finite `float`, `str`, and lists and str-keyed dicts of those; anything else is refused.
- **`sidecar(view, artifact, *, directory=None)`** writes the commitment view as YAML (spec
  §8.8.3) beside the artifact: every field `view` printed except the inline `package` and a
  served bundle's `trustRegistry`, which are not §8.8.1 fields. The file is named
  `<artifact's file name>.record.yaml`, extension kept (`analysis.ipynb.record.yaml`): the spec's
  `<artifact-basename>` does not say whether the extension stays, and keeping it is the POSIX
  basename and cannot collide when two artifacts share a stem (`analysis.ipynb` beside
  `analysis.py`).
- **`show(record, result=None, *, role_path=("role",), marimo=False)`** renders a record (what
  `view` or `sign` printed) with its `verify --json` result: the type, the role, the signer,
  the hash, `createdAt`, the `vcsRef` (marked as asserted and not fetched), the status with its
  reason or successor, one line per check, and a sentence saying that verification does not say
  the analysis is correct. Without `result` it runs `verify`. In Jupyter it returns an object
  with `_repr_html_`; with `marimo=True`, `mo.Html`. The role is a signed assertion the signer
  made, read from the package's `extensions` at `role_path` (by default `extensions["role"]`, a
  string or a list of strings); `show` labels it as the signer's and checks nothing about it.

The notebook helpers edit the notebook as JSON, splicing the new cell into `cells` so every
other byte of the file stays as written. `httpx` is imported only inside `pin` and the publish
calls, PyYAML only
inside `sidecar`, and `marimo` only inside a Marimo call; `IPython`, `marimo` and `nbformat`
are not dependencies.

## Publishing to a GitHub Pages host

`publish` writes a signed record to a GitHub repository made from the
[host template](https://github.com/npstorey/typedstandards-host-template) in its publish mode,
whose workflow builds the site from the repository's `host.json` and deploys it to GitHub Pages.
Each call is one commit, made through GitHub's Git Data API; the host's workflow then builds and
deploys it. `publish` does not wait for the deploy. The template's README sets a host up for this:
[Publishing from a notebook](https://github.com/npstorey/typedstandards-host-template#publishing-from-a-notebook).

That setup names your key in `host-policy.json`'s `signer`, and `publish` refuses a record signed
by any other key. The CLI prints a `did:key` only in what it signs, so read yours from the first
record you sign, before its first publish:

```python
signed = ts.sign(record, output_file="dog-licensing.ipynb")
signed["package"]["signer"]["identifier"]  # did:key:z6Mk…: the policy's signer
```

A copy starts with no records; its first publish adds the first.

```python
import typedstandards as ts

host = ts.GitHubPagesHost("owner/repo")  # branch="main"; the token from TYPEDSTANDARDS_GITHUB_TOKEN
signed = ts.sign(record, output_file="dog-licensing.ipynb")  # record: an envelope input, as under Use
receipt = ts.publish(signed, host=host, notebook="dog-licensing.ipynb", title="Dog licensing by district")
receipt["verify_url"]  # the verifier's link for the served bundle

withdrawal = ts.withdraw(
    {"targetNodeId": signed["envelopeHash"], "reason": "...", "signer": signed["package"]["signer"]}
)
ts.publish_attestation(withdrawal, host=host, name=receipt["name"])
```

- **`GitHubPagesHost(repository, *, branch="main", token=None, ...)`**: the repository as
  `owner/name`. Its `repr` shows the repository and the branch only, and its errors never quote
  an argument. A repository or branch with a part shaped like a GitHub token (a token prefix such
  as `ghp_` or `github_pat_`, then 30 or more token characters) is refused; a short name with such
  a prefix, such as `ghp_notes`, is accepted. The HTTP client a call builds
  ignores proxy and certificate environment variables; pass `client=` (an `httpx.Client`) for
  those.
- **`publish(signed, *, host, title, name=None, notebook=None, role="notebook", revises=None)`**
  writes what `sign` printed (or its path) to `records/<name>.signed.json` and appends its entry to
  `host.json`: `{name, signed, attestations: [], title, extensions: {role}}`. `host.json` is
  rewritten with two-space indentation; no other field of it changes.
- **`publish_attestation(node, *, host, name)`** writes what `withdraw` or `attest` printed (or
  its path) to `records/<name>.<kind>-<eight hex of its nodeId>.json` and adds that path to the
  record's `attestations`, in one commit. A node already listed there is not written again.

### Names

The **default name**, with `notebook=`, is `<stem>/<date>-<eight hex>`: the notebook file's stem,
the date of the record's `createdAt` (UTC), and the first eight hex characters of its
`envelopeHash`, for example `dog-licensing/2026-10-04-ebb38315`. The signed document does not carry
the notebook's file name, so the stem comes from the argument. A rerun signs to another
`envelopeHash`, so it gets a new name.

A record whose `envelopeHash` the host already lists is not written again, under any name: the
call writes nothing (`written: False`), and its receipt names the entry that lists it, with that
entry's `bundle_url` and `verify_url`. host-core's build refuses one `envelopeHash` listed twice,
so a second entry would stop every later deploy. To find a listed hash, each call makes one read of
each listed record's signed file.

With an explicit `name=`, a name listed with another record is refused, unless `revises=` is
given. Then the
record is written under `<name>-<its first eight hex>`, and the `revises=` node goes on the listed
record's entry, in the same commit. Sign the node first:

```python
node = ts.attest(
    {
        "type": "attestation/revises/v1",
        "targetNodeId": prior["envelopeHash"],  # the listed record
        "successorNodeId": signed["envelopeHash"],  # this one
        "signer": signed["package"]["signer"],
    }
)
ts.publish(signed, host=host, name="dog-licensing", title="Dog licensing, rerun", revises=node)
```

`publish` compares the node's fields only: its type, its `successorNodeId` with this record's
`envelopeHash`, and its `targetNodeId` with the listed record's. Under the default name, a
`revises=` node goes on the entry of the listed record it targets.

A name is `/`-separated segments of letters, digits, `.`, `_` and `-`, with no `.` or `..`
segment (host-core's rule), and no `records` or `evidence` segment, which the verifier reads as a
record page's URL rather than a bundle's.

### Refusals

Each raises `typedstandards.PublishRefusedError` before any write request:

- a token that does not start `github_pat_`, or that holds whitespace, a quote or `op://` (the
  message names where the token came from, never its value);
- a name that fails the rule above, or a bundle URL with a `records` or `evidence` segment;
- an empty title;
- a record whose `output` is a BlobRef (signed with `output_url=`): the host serves the signed
  file only, so sign with `output_file=` alone;
- a record or node whose signer is not the `signer` in the host's `host-policy.json`, or whose
  type the policy does not name;
- a role that no rule for `active` records in `host-policy.json` admits: such a record would fail
  the host's build, and with it every later deploy;
- a listed name with another record and no `revises=`, or a `revises=` whose fields do not match;
- anything host-core's build would refuse once the commit lands: a signed file it cannot read as
  UTF-8 JSON; a signature without its `signature` and `publicKey`, or with a `kid` other than the
  signer; an empty `createdAt`; under a registry, a signer, display name or key other than the
  host's first record's; with `registry: null`, a signer that is not a pseudonymous `did:key`; a
  path another entry already names; a `host.json` that fails host-core's manifest rule; and a host
  whose build already fails on a listed record;
- for `publish_attestation`, a withdrawal or supersession that would leave the record in a status
  no rule of `host-policy.json` displays (the template's policy has no rule for `superseded`); and
  a claim-to-claim node (`corroborates`, `contradicts`), a name the
  host does not list, or a node whose `targetNodeId` is not that record's `envelopeHash`.

A ref update GitHub does not accept re-reads the branch head first, since a write that errored may
have landed. If the commit did not land and the branch moved, `publish` plans again from the new
head once; a second failure raises `typedstandards.PublishError`, as does an API error, whose
message names the request and GitHub's own message.

### The receipt

| Key | Value |
|---|---|
| `name` | the name the record is listed under (the derived name for a revision) |
| `commit` | the new commit's id, or `None` when nothing was written |
| `bundle_url` | `<origin>/bundles/<name>.bundle.json`, from `host.json`'s `origin` |
| `verify_url` | the verifier's link for `bundle_url`, the same link `badge_cell` writes |
| `registry_url` | `<origin>/.well-known/typed-publisher.json`, or `None` for a host with no registry |
| `written` | `True` for a new commit, `False` when the host already listed it |
| `run` | `None`: `publish` does not wait for the deploy |

### The token

A fine-grained personal access token, for the one publishing repository, with **Contents: read
and write** and nothing else (enough for a public repository; a private one is unmeasured). Give
it an expiry. It comes from `token=`, else from `TYPEDSTANDARDS_GITHUB_TOKEN`, read when a publish
runs; it is added to each request's `Authorization` header by an `httpx.Auth` that holds it and
withholds it from its `repr`, whether the call builds its client or uses one given as `client=`. It
is in no message, log record, receipt or file. When an exception escapes a request, the locals of
the frames it carries, httpx's, httpcore's and h11's included, are cleared before it propagates,
so a traceback with frame locals does not show the token; the tests check this with httpx's mock
transport and with its real transport over a failing stream. Never write it as a literal in a cell. Locally,
set it with the seed, from the secret store that starts the kernel (`op run --env-file=… --
jupyter lab`); in a hosted notebook, from the hosting service's secret store, as for the seed
below.

Commits made through the API are unsigned, so a branch rule that requires signed commits or pull
requests refuses them. The template's README gives the ruleset for a publishing branch: no
deletion and no force push.

### The seed in a hosted notebook

A hosted kernel has no launcher to set the seed's variable, so the author's own code sets it, in
one cell that prints nothing:

```python
import os

os.environ["TYPEDSTANDARDS_SIGNING_SEED_B64"] = read_secret("TYPEDSTANDARDS_SIGNING_SEED_B64")
```

where `read_secret` stands for the hosting service's own call that reads a stored secret. The
wrapper still never reads the variable; the CLI does.

The seed must never be pasted into a cell, printed (by `print`, `%env`, or a cell whose last
expression is the value), or saved in the `.ipynb` in any other way: the notebook is the file that
is signed and published. In a hosted notebook, the hosting service's runtime holds the seed for as
long as the kernel runs. Make the seed once, outside any notebook (`openssl rand -base64 32`), and
keep it in a password manager as well as the service's secret store: a record signed by a key that
is lost can never be withdrawn or revised.

In GitHub Codespaces, a Codespaces secret named `TYPEDSTANDARDS_SIGNING_SEED_B64` arrives in the
codespace as an environment variable, so no line is needed; neither a repository Actions variable
nor an Actions secret is a place for the seed.

## Versions

Each wrapper release pins one CLI version exactly. A CLI upgrade reaches users as a wrapper release
that moves the pin.

## Development

See [CLAUDE.md](https://github.com/npstorey/typedstandards-python/blob/main/CLAUDE.md) for the development loop and the checks CI runs.

## License

MIT. The wheel also carries each vendored npm package's own licence file: five are MIT, and
`canonicalize` is Apache-2.0.
