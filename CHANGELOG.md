# Changelog

## Unreleased

- Fixed: every mapping input to `sign`, `withdraw`, `attest` and `verify` reaches the CLI as a
  temporary file, removed before the call returns, and no longer on standard input. A document
  larger than a pipe buffer holds, such as a served bundle that signs a notebook inline, failed
  with `UsageError` (`--input - cannot be read: EAGAIN`) (npstorey/typedstandards-python#6,
  npstorey/typedstandards#138). `verify` still drops only a bundle's top-level `trustRegistry`.

## 0.1.0 — 2026-10-04

- `sign`, `withdraw`, `attest`, `view` and `verify`: pass-throughs to `@typedstandards/cli` 0.2.0,
  vendored into the wheel at build time and run as a child process with the inherited environment.
  Each returns the CLI's stdout parsed as JSON.
- A Node locator: `TYPEDSTANDARDS_NODE`, then `node` on `PATH`; floor 20.19.0.
- Exit codes 1 to 4 raise `VerificationError`, `UsageError`, `SeedError` and `InternalError`, under
  `CliError`; a missing or old Node raises `NodeLocatorError`.
- `verify` drops a bundle's top-level `trustRegistry` before the CLI sees it (typedstandards#136).
- `CLI_VERSION = "0.2.0"` and `cli_version()`.
- `pin(url)`: fetches once and returns the bytes with a `queries[]` retrieval entry (`url`,
  `sha256`, `bytes`, `httpStatus`, `fetchedAt`; `rowsUpdatedAt` and `datasetId` for a portal
  resource); `save=` writes both.
- `badge_cell`: the verifier badge as a notebook's first cell, or a `mo.md` cell's source; no hash
  and no time in the cell.
- `comparison_cell`: the spec §8.7.4 comparison cell, appended as the last cell; values must be
  literals.
- `sidecar`: `<artifact file name>.record.yaml` from `view`'s output, without `package` and
  `trustRegistry`.
- `show`: HTML for Jupyter (`_repr_html_`) or Marimo (`mo.Html`) from a record and its
  `verify --json` result.
- `badge_cell` no longer reads a URL's host and port as a time: `https://192.168.1.10:8080/…` is
  accepted. A date or time in the URL's path, query or fragment (as written or percent-encoded) or
  in a fact is refused.
- README: only the calls that run the CLI need Node (the five commands, `cli_version()`, and
  `show` without a result); its links are absolute, so they resolve on the PyPI page.
