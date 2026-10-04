#!/usr/bin/env bash
# Publish typedstandards to PyPI (typedstandards#135, G0 D4 = A). The owner runs this, in their own
# terminal, from a clean checkout of main at the release commit. It never prints the token.
#
#   DRY_RUN=1 scripts/publish.sh
#       Checks the checkout, the version and the CHANGELOG heading, and that PyPI does not have this
#       version yet. Builds the sdist and the wheel into dist/, checks them, installs the wheel into
#       a fresh environment and runs the smoke check there, then runs `uv publish --dry-run`.
#       Prints each file's SHA-256 and the live command. Uploads nothing.
#
#   op run --env-file=pypi.env -- scripts/publish.sh
#       Uploads exactly the files the dry run built and checked: dist/ must match dist/SHA256SUMS
#       and the commit the dry run recorded. Then reads the release back from PyPI for about five
#       minutes, and installs it into a fresh environment, which must print CLI_VERSION.
#       pypi.env holds a 1Password reference, never a value:
#           UV_PUBLISH_TOKEN=op://<vault>/<item>/<field>
#
#   READ_BACK=1 scripts/publish.sh
#       Only the read-back and the fresh-environment check, for a run that stopped after uploading.
#
# Overrides, for testing the script itself: RELEASE_REF (the ref HEAD must equal; default
# origin/main), PACKAGE and VERSION (default this package and its __version__), DIST (default
# dist), READ_BACK_SECONDS (default 300), CHECK_INSTALL=0 (skip the fresh-environment install).

set -euo pipefail

say() { printf 'publish: %s\n' "$*"; }
die() { printf 'publish: %s\n' "$*" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PACKAGE="${PACKAGE:-typedstandards}"
VERSION="${VERSION:-$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/typedstandards/__init__.py)}"
CLI_VERSION="$(sed -n 's/^CLI_VERSION = "\(.*\)"$/\1/p' src/typedstandards/__init__.py)"
DIST="${DIST:-dist}"
RELEASE_REF="${RELEASE_REF:-origin/main}"
READ_BACK_SECONDS="${READ_BACK_SECONDS:-300}"
CHECK_INSTALL="${CHECK_INSTALL:-1}"
PYPI="https://pypi.org"
SDIST="$PACKAGE-$VERSION.tar.gz"
WHEEL="$PACKAGE-$VERSION-py3-none-any.whl"

sha256_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

# The JSON PyPI serves for this version, or nothing when it does not have it (yet).
pypi_release_json() { curl -sf --max-time 30 "$PYPI/pypi/$PACKAGE/$VERSION/json" || true; }

# Print what PyPI lists for each file in $DIST/SHA256SUMS. Exit 0 when every file is listed with the
# same SHA-256, 2 when any is listed with a different one, 1 when any is not listed yet.
pypi_matches_sums() {
  local json
  json="$(pypi_release_json)"
  [ -n "$json" ] || { say "PyPI does not list $PACKAGE $VERSION yet"; return 1; }
  JSON="$json" uv run --no-project --quiet python - "$DIST/SHA256SUMS" <<'PY'
import json, os, sys
listed = {f["filename"]: f["digests"]["sha256"] for f in json.loads(os.environ["JSON"])["urls"]}
missing = different = False
for line in open(sys.argv[1], encoding="utf-8"):
    digest, name = line.split()
    name = name.lstrip("*")
    seen = listed.get(name)
    state = "same SHA-256" if seen == digest else ("not listed yet" if seen is None else f"DIFFERENT SHA-256 {seen}")
    print(f"publish:   {name}  {digest}  PyPI: {state}")
    missing = missing or seen is None
    different = different or (seen is not None and seen != digest)
sys.exit(2 if different else 1 if missing else 0)
PY
}

read_back() {
  [ -f "$DIST/SHA256SUMS" ] || die "$DIST/SHA256SUMS is missing: it is written by the dry run"
  say "reading $PACKAGE $VERSION back from $PYPI, for up to $READ_BACK_SECONDS seconds"
  local deadline=$((SECONDS + READ_BACK_SECONDS))
  while :; do
    local rc=0
    pypi_matches_sums || rc=$?
    [ "$rc" -eq 0 ] && break
    if [ "$rc" -eq 2 ]; then
      say "PyPI lists a file of $PACKAGE $VERSION with a different SHA-256 from the file built here,"
      say "so what PyPI serves is not this build. A version cannot be uploaded twice: do not retry."
      say "Compare $DIST/SHA256SUMS with $PYPI/project/$PACKAGE/$VERSION/#files"
      exit 2
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      say "PyPI has not listed every file with these hashes within $READ_BACK_SECONDS seconds."
      say "An upload can take longer to appear; this alone does not mean it failed."
      say "Run the read-back again: READ_BACK=1 scripts/publish.sh"
      exit 1
    fi
    sleep 15
  done
  say "read back: PyPI lists $PACKAGE $VERSION with the SHA-256 of every file built and checked"
  [ "$CHECK_INSTALL" = "1" ] || return 0
  say "installing $PACKAGE==$VERSION from PyPI into a fresh environment"
  local tmp printed
  tmp="$(mktemp -d)"
  until printed="$(cd "$tmp" && env -u UV_PUBLISH_TOKEN uv run --no-project --isolated --refresh --quiet \
    --with "$PACKAGE==$VERSION" python -c 'import typedstandards; print("CLI_VERSION", typedstandards.CLI_VERSION)' 2>/dev/null)"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      say "the index has not served $PACKAGE==$VERSION to uv yet; the read-back above found it."
      say "Run the read-back again in a few minutes: READ_BACK=1 scripts/publish.sh"
      exit 1
    fi
    sleep 15
  done
  rm -rf "$tmp"
  say "fresh environment: $printed"
  [ "$printed" = "CLI_VERSION $CLI_VERSION" ] || die "expected CLI_VERSION $CLI_VERSION"
}

if [ "${READ_BACK:-0}" = "1" ]; then
  read_back
  exit 0
fi

# --- the checks both the dry run and the live run make -------------------------------------
for tool in git uv node npm curl shasum; do
  command -v "$tool" >/dev/null || die "$tool is not on PATH"
done
[ -z "$(git status --porcelain --untracked-files=normal)" ] || die "the checkout has changes; publish from a clean checkout"
git fetch --quiet origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse "$RELEASE_REF")" ] ||
  die "HEAD $(git rev-parse --short HEAD) is not $RELEASE_REF $(git rev-parse --short "$RELEASE_REF"); publish from the release commit"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "__version__ is '$VERSION', not a release version (X.Y.Z)"
heading="$(grep -m1 -E "^## $VERSION — [0-9]{4}-[0-9]{2}-[0-9]{2}$" CHANGELOG.md || true)"
[ -n "$heading" ] || die "CHANGELOG.md has no heading '## $VERSION — <date>'"
dated="${heading##* }"
status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$PYPI/pypi/$PACKAGE/$VERSION/json")"
case "$status" in
  404) ;;
  200) die "PyPI already has $PACKAGE $VERSION: a version is uploaded once. To check it: READ_BACK=1 scripts/publish.sh" ;;
  *) die "PyPI answered $status for $PACKAGE $VERSION; try again" ;;
esac
say "checkout $(git rev-parse --short HEAD) = $RELEASE_REF; $PACKAGE $VERSION (CHANGELOG dated $dated); not on PyPI yet"

if [ "${DRY_RUN:-0}" = "1" ]; then
  rm -rf "$DIST"
  say "building the sdist, and the wheel from it (the build vendors @typedstandards/cli with npm ci)"
  uv build --out-dir "$DIST"
  [ "$(ls "$DIST" | sort)" = "$(printf '%s\n%s\n' "$SDIST" "$WHEEL" | sort)" ] || die "$DIST holds $(ls "$DIST" | tr '\n' ' '), not $SDIST and $WHEEL"
  uv tool run --quiet twine check --strict "$DIST/$SDIST" "$DIST/$WHEEL"
  WHEEL_PATH="$DIST/$WHEEL" CLI_VERSION="$CLI_VERSION" uv run --no-project --quiet python - <<'PY'
import json, os, sys, zipfile
names = zipfile.ZipFile(os.environ["WHEEL_PATH"]).namelist()
cli = "typedstandards/_vendor/node_modules/@typedstandards/cli/package.json"
if cli not in names:
    sys.exit("publish: the wheel does not carry the vendored CLI")
version = json.loads(zipfile.ZipFile(os.environ["WHEEL_PATH"]).read(cli))["version"]
if version != os.environ["CLI_VERSION"]:
    sys.exit(f"publish: the wheel vendors @typedstandards/cli {version}, not {os.environ['CLI_VERSION']}")
vendored = sum(1 for n in names if "/_vendor/node_modules/" in n)
print(f"publish: the wheel vendors @typedstandards/cli {version} ({vendored} files)")
PY
  tmp="$(mktemp -d)"
  uv venv --quiet "$tmp/venv"
  uv pip install --quiet --python "$tmp/venv" "$DIST/$WHEEL"
  say "smoke check from the installed wheel, with a throwaway seed"
  env -u UV_PUBLISH_TOKEN TYPEDSTANDARDS_SIGNING_SEED_B64="$(openssl rand -base64 32)" "$tmp/venv/bin/python" scripts/smoke_wheel.py
  rm -rf "$tmp"
  (cd "$DIST" && shasum -a 256 "$SDIST" "$WHEEL" > SHA256SUMS)
  git rev-parse HEAD > "$DIST/COMMIT"
  # Without a token, uv publish --dry-run still checks the files and the command line.
  env -u UV_PUBLISH_TOKEN uv publish --dry-run --token dry-run "$DIST/$SDIST" "$DIST/$WHEEL"
  say "built and checked, at $(cat "$DIST/COMMIT"):"
  sed 's/^/publish:   /' "$DIST/SHA256SUMS"
  say "DRY_RUN: nothing was uploaded. To upload these two files:"
  say "  op run --env-file=pypi.env -- scripts/publish.sh"
  exit 0
fi

# --- the live run ---------------------------------------------------------------------------
[ -n "${UV_PUBLISH_TOKEN:-}" ] || die "UV_PUBLISH_TOKEN is not set: run through op run --env-file=pypi.env"
[ "$dated" = "$(date +%F)" ] || die "CHANGELOG.md dates $VERSION $dated, and today is $(date +%F): the heading names the publish day"
[ -f "$DIST/SHA256SUMS" ] && [ -f "$DIST/COMMIT" ] || die "run DRY_RUN=1 scripts/publish.sh first: the live run uploads what it built"
[ "$(cat "$DIST/COMMIT")" = "$(git rev-parse HEAD)" ] || die "$DIST was built at $(cat "$DIST/COMMIT"), not HEAD; run the dry run again"
(cd "$DIST" && shasum -a 256 -c SHA256SUMS) || die "$DIST does not match SHA256SUMS; run the dry run again"
say "uploading $SDIST and $WHEEL"
set +e
uv publish --check-url "$PYPI/simple/" "$DIST/$SDIST" "$DIST/$WHEEL"
code=$?
set -e
if [ "$code" -ne 0 ]; then
  say "uv publish exited $code. An upload can land even when the command fails."
  say "Before any retry, check what PyPI has: READ_BACK=1 scripts/publish.sh"
  exit "$code"
fi
read_back
