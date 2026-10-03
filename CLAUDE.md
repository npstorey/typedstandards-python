# CLAUDE.md

`typedstandards` on PyPI: a thin Python wrapper that runs `@typedstandards/cli` (vendored, pinned
exactly in `package.json` and `package-lock.json`) as a child process. Python `>=3.11`; hatchling
with a build hook (`hatch_build.py`) that vendors the CLI; `uv` for everything.

## Development loop

The system `python3` may be older than 3.11: run Python only through `uv`. Under a Node version
manager a non-interactive shell may have no `node` on `PATH`; load it first
(`eval "$(fnm env)" && fnm use 24`, or your equivalent).

- `uv sync` — creates `.venv` and installs the package editable. The build hook runs
  `npm ci --omit=dev --ignore-scripts` into `src/typedstandards/_vendor/` (git-ignored), so tests
  drive the same tree a wheel ships, never a global CLI or `npx`. It re-runs when `pyproject.toml`,
  `package.json`, `package-lock.json` or `hatch_build.py` change; force it with
  `uv sync --reinstall-package typedstandards`.
- Another Python: `uv run --python 3.11 pytest`. Another Node: put it first on `PATH`, or set
  `TYPEDSTANDARDS_NODE`.

The checks CI runs (`.github/workflows/ci.yml`):

- `test (py<3.11|3.12|3.14>, <ubuntu-24.04|macos-15>, node 24)` and
  `test (py3.12, ubuntu-24.04, node 22)` — `uv sync --locked`, then `uv run pytest`; the gate is
  `0 failed`.
- `lint` — `uv run ruff check .` and `uv run ruff format --check .`.
- `wheel (build, install, smoke)` — `uv build` (the sdist, then the wheel from it), the wheel
  installed into a fresh environment, and `scripts/smoke_wheel.py` run there with a throwaway seed.

## Node floors

The wrapper and the CLI need Node 20.19 or later (the CLI's `engines.node`). A
`@typedstandards/host-core` site build needs Node 22 or later. The README states both.

## The wrapper holds no key

It holds no key, reads no signing seed, and computes none of the format's hashes (content hash,
envelope hash, node id): the CLI reads `TYPEDSTANDARDS_SIGNING_SEED_B64` from the environment it
inherits and does all of the format's work. Guard tests, which must keep failing on an offender:

- `tests/test_guards.py` with `tests/guards.py`: no module under `src/typedstandards` names the
  seed variable; no call passes `env=` or changes the process environment; no module imports
  `hashlib` (or `hmac`, or hashlib's underscore modules) except P2's `pin.py`, whose digest is a
  signed assertion; at run time, every child inherits the environment unchanged and the wrapper
  never reads the seed variable. Each scanner is also driven over a tree of offenders.

Test code may generate a random seed and set it with `monkeypatch.setenv`; package code never
touches one. A failing test never prints environment values.

## Secret hygiene

Never `cat`/`head`/`tail`/dump `.env*`, `auth.json`, `credentials*`, `*.pem`, `*.key`, `~/.ssh`,
`~/.aws`. Read only by key **name** (`grep`/`jq` a field, never a value) or a command the tool
exposes; never load-and-print a credentials file, even redacted.

## Evidence protocol (gated sprint phases)

Every phase report (PR body and anchor-issue comment) carries:

- the phase **branch**, head SHA and `git diff --numstat main...HEAD`, with the blast zone stated;
- each acceptance criterion's **red** (the failing assertion's output) and its **green**, pasted;
- the **full suite output** on every Python and Node the matrix names, the clean-checkout wheel
  build and its smoke check, and gitleaks over the outgoing range;
- **fixture provenance**: each fixture's source, commit and SHA-256 (`tests/fixtures/README.md`),
  with the byte-equal assertions called out;
- the **model** the phase ran on; everything flagged and not fixed.

The orchestrator re-verifies evidence before merging; numbers an implementer reports do not pass a
gate on their own.

## Rollback tags

Bracket every phase merge: `rollback/pre-produce-py-p<n>` at the pre-merge anchor and
`rollback/produce-py-p<n>-merged` at the merge commit. The orchestrator pushes them, not
implementation sessions.

## Push guard

A global pre-push guard (gitleaks plus a keyword list) scans the added lines of every outgoing
commit, so a fix on top does not clear an earlier commit: the flagged bytes must be absent from all
pushed history. Pushes go to the owner as one command, after `gitleaks git --log-opts="main..HEAD"`
over the outgoing range is clean. Never bypass the guard and never tune its patterns on your own
initiative. `.gitleaks.toml` allows only Ed25519 `did:key` identifiers, which are public keys.

## Phrasing, commits, merges, releases

- Neutral phrasing everywhere: no stakeholder, organisation or person is named. This repository is
  public and its history is permanent.
- `git commit -s` on every commit; the `Signed-off-by:` email must equal the author email exactly.
  Commits are signed (SSH).
- Work lands by PR to `main` as merge commits; never push to `main`. Merging is the orchestrator's
  call on evidence in a gated sprint, the owner's otherwise.
- Publishing to PyPI is the owner's act, from a tested script with a `DRY_RUN` mode.
- A CLI upgrade reaches users as a wrapper release that moves the pin: `package.json`,
  `package-lock.json` (`npm install --package-lock-only --ignore-scripts`) and `CLI_VERSION`
  together; `tests/test_version.py` fails on any one left behind.
- `CHANGELOG.md` is a factual per-version record; changes collect under `## Unreleased`.
