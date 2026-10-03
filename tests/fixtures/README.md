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
