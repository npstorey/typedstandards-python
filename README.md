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
`TYPEDSTANDARDS_NODE`. `pin`, `badge_cell`, `comparison_cell`, `sidecar` and
`show(record, result)` run without Node.

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

Each function returns the CLI's stdout parsed as JSON. An input may be a mapping (sent to the CLI
as JSON on standard input) or the path of a JSON file.

| Function | CLI command | Returns |
|---|---|---|
| `sign(input, *, output_file=None, output_url=None, content_type=None)` | `sign` | `{package, envelopeHash, signature}` |
| `withdraw(input)` | `withdraw` | `{node, nodeId, signature}` |
| `attest(input)` | `attest` | `{node, nodeId, signature}` |
| `view(signed, *, visibility, attestations=(), trust_registry_url=None, package_url=None, title=None)` | `view` | the commitment view, package inline |
| `verify(input, *, blobs=(), full=True)` | `verify` (`--json` when `full`) | `{ok, nodeId, failures, checks, lifecycle}` |

`view` writes the mappings it is given to temporary files, removed before it returns. The CLI's
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
other byte of the file stays as written. `httpx` is imported only inside `pin`, PyYAML only
inside `sidecar`, and `marimo` only inside a Marimo call; `IPython`, `marimo` and `nbformat`
are not dependencies.

## Versions

Each wrapper release pins one CLI version exactly. A CLI upgrade reaches users as a wrapper release
that moves the pin.

## Development

See [CLAUDE.md](https://github.com/npstorey/typedstandards-python/blob/main/CLAUDE.md) for the development loop and the checks CI runs.

## License

MIT. The wheel also carries each vendored npm package's own licence file: five are MIT, and
`canonicalize` is Apache-2.0.
