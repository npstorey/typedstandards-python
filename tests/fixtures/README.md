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
