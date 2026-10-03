# Changelog

## Unreleased

- `sign`, `withdraw`, `attest`, `view` and `verify`: pass-throughs to `@typedstandards/cli` 0.2.0,
  vendored into the wheel at build time and run as a child process with the inherited environment.
  Each returns the CLI's stdout parsed as JSON.
- A Node locator: `TYPEDSTANDARDS_NODE`, then `node` on `PATH`; floor 20.19.0.
- Exit codes 1 to 4 raise `VerificationError`, `UsageError`, `SeedError` and `InternalError`, under
  `CliError`; a missing or old Node raises `NodeLocatorError`.
- `verify` drops a bundle's top-level `trustRegistry` before the CLI sees it (typedstandards#136).
- `CLI_VERSION = "0.2.0"` and `cli_version()`.
