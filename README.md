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

With no Node, or one older than 20.19.0, every call raises `typedstandards.NodeLocatorError`, whose
message names the floor and `TYPEDSTANDARDS_NODE`.

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

## Versions

Each wrapper release pins one CLI version exactly. A CLI upgrade reaches users as a wrapper release
that moves the pin.

## Development

See [CLAUDE.md](CLAUDE.md) for the development loop and the checks CI runs.

## License

MIT. The wheel also carries each vendored npm package's own licence file: five are MIT, and
`canonicalize` is Apache-2.0.
