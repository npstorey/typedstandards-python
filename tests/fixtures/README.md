# Test fixtures

Each file is a verbatim copy, byte for byte, of a file in another repository at a stated commit.
A test pins each copy's SHA-256, so a changed byte fails the suite. JSON takes no comments, so the
provenance is recorded here.

| File | Source | Read at | Last changed at | SHA-256 | Pinned by |
|---|---|---|---|---|---|
| `reference-golden.json` | `npstorey/typedstandards`, `packages/produce-core/src/__fixtures__/reference-golden.json` | `116882a` | `ea75a1d` | `d2bcfc2bc017b07502b3b00c3aa16de402df134128a374b4582650b79fb501c1` | `tests/test_golden.py` |
| `first-note.bundle.json` | `npstorey/typedstandards-host-template`, `docs/bundles/first-note.bundle.json` | `70bfd18` | `26dff9b` | `cb11d2a229c9695db6c7f4d6c9349ccee14f14af6c39844886480699ba2401ba` | `tests/test_d9.py` |

Re-derive either copy with `git -C <repository> show <commit>:<path> > tests/fixtures/<file>`.

- **`reference-golden.json`** holds 9 envelope cases and 6 attestation cases, captured from the
  reference implementation as its `_meta` records. No npm tarball ships it, so the tests carry
  this copy. `tests/test_golden.py` replays the 9 envelope cases through `sign` and the
  `withdraws` case through `withdraw`. It carries the reference platform's own identifiers, as it
  does in its source repository.
- **`first-note.bundle.json`** is the bundle the host template serves, written by
  `@typedstandards/host-core` 0.1.1 with a top-level `trustRegistry`. `tests/test_d9.py` verifies
  it through the wrapper, which drops that key before the CLI sees it (typedstandards#136).

## Captured outputs

These files are not copies of another repository's file: each is the output of a stated command,
captured once and committed. A test pins each one's SHA-256 too.

| File | Captured from | Command | Date | SHA-256 | Pinned by |
|---|---|---|---|---|---|
| `badge-golden.json` | `@typedstandards/host-core`'s `links.ts` at typedstandards `116882a` (`packages/host-core/src/links.ts`), run by Node 24.21.0 | below | 2026-10-03 | `bd70f819249e8f8a5f3cf1245cbd521c32e3671623a4d3d6e009f71ae6661eaa` | `tests/test_badge.py` |
| `record-active.signed.json` | the wrapper's `sign`, through the vendored `@typedstandards/cli` 0.2.0, Node 24.21.0 | `capture_records.py` | 2026-10-03 | `6a43fcbbd205a94ad71b94c7600b61c740177568b345af2744a947236285abfc` | `tests/test_fixtures.py` |
| `record-active.bundle.json` | the wrapper's `view` of the above | `capture_records.py` | 2026-10-03 | `aa75bd9ad6f7c101ee2c3a96373e97826e6fae6dfa172bdc1e84bf69efcf5937` | `tests/test_fixtures.py` |
| `record-active.verify.json` | the wrapper's `verify` (`--json`) of the bundle | `capture_records.py` | 2026-10-03 | `a37890a4413b0ff206b0fc19f0cc998732c6b9590d504d5639b7ebbf3fccc833` | `tests/test_fixtures.py` |
| `record-withdrawn.signed.json` | the wrapper's `sign`, as above | `capture_records.py` | 2026-10-03 | `cbc91d561707f1e10034ff01a5cd587fb52276bae79f626665b14aa8d4bf5a9b` | `tests/test_fixtures.py` |
| `record-withdrawn.withdrawal.json` | the wrapper's `withdraw` of that record, same key | `capture_records.py` | 2026-10-03 | `42bfe9b0ee86ba5b219c62a472a1d0e8ee45b5191fc7a7dd8cde842b69859a2e` | `tests/test_fixtures.py` |
| `record-withdrawn.bundle.json` | the wrapper's `view` of the record with the withdrawal | `capture_records.py` | 2026-10-03 | `33b608d24e36beca3314fde938513252380e2ffbeaff3312e4dcb4f58482d2eb` | `tests/test_fixtures.py` |
| `record-withdrawn.verify.json` | the wrapper's `verify` (`--json`) of the bundle | `capture_records.py` | 2026-10-03 | `8b882a0bc06300add88b5186b11861279a1f6505f80344d1c279aa1eaa3ad4ef` | `tests/test_fixtures.py` |

- **`badge-golden.json`** holds six bundle URLs, each with what host-core's own
  `buildVerifyHref(CANONICAL_ORIGIN, url)` and `buildEmbedMarkdown(CANONICAL_ORIGIN, url)`
  return for it. The URLs cover the characters `encodeURIComponent` leaves unescaped, a space and
  query characters, non-ASCII text and a literal `%`, and the characters it must escape. The first
  is the host template's served bundle, whose Markdown is the template's README line 9 at
  `70bfd18`. `tests/test_badge.py` asserts the wrapper's link and Markdown equal each case byte for
  byte. To re-capture: write `links.ts` out with
  `git -C <typedstandards> show 116882a:packages/host-core/src/links.ts > links.ts`, then run with
  Node 24 (which strips the file's types) a module that imports `buildVerifyHref`,
  `buildEmbedMarkdown` and `CANONICAL_ORIGIN` from `./links.ts`, maps the six URLs to
  `{url, verify, markdown}`, and prints `JSON.stringify({ cases }, null, 1)` and a newline.

- **`record-*.json`** are two records signed through the wrapper under a throwaway seed, generated
  for the capture and never stored: an active analysis notebook (a synthetic notebook with the
  badge cell and the comparison cell, role `analysis`) and a claim (role `claim`), withdrawn by
  the same key with a stated reason. Each carries a `vcsRef` to a fictional repository and its
  role under `extensions`. The command, run from the repository root on 2026-10-03 with Node
  24.21.0 and the vendored CLI 0.2.0:

  ```sh
  TYPEDSTANDARDS_SIGNING_SEED_B64="$(openssl rand -base64 32)" uv run python tests/fixtures/capture_records.py
  ```

  A new run signs with a new key, so it writes different signatures, `did:key`s and hashes, and
  the pinned SHA-256s must be updated with it. The documents carry the throwaway key's public
  `did:key`, which `.gitleaks.toml` allows. `tests/test_fixtures.py` checks that the vendored CLI's
  `verify --json` of each bundle still equals the captured document; `tests/test_sidecar.py` builds
  a fresh `view` from each `*.signed.json` through the CLI; `tests/test_show.py` renders from the
  captured bundles and `verify` documents without Node.
