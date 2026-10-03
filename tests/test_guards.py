"""Acceptance 2: the wrapper reads no seed, passes its child no environment but the inherited
one, and imports no digest module.

Each rule is checked statically (guards.py scans the package's source) and the first two at run
time as well (the wrapper's child processes and its environment reads are recorded while it
drives the real CLI). Each scanner is also driven over a tree of offending modules, so a guard
that can no longer fail is itself a failure.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

import pytest
from guards import env_overrides, hash_imports, seed_references
from support import SEED_VARIABLE, self_certifying_input

import typedstandards

PACKAGE = Path(typedstandards.__file__).parent


# --- statically, over the package -------------------------------------------------------------


def test_package_names_no_seed_variable() -> None:
    assert seed_references(PACKAGE) == []


def test_package_passes_no_environment() -> None:
    assert env_overrides(PACKAGE) == []


def test_package_imports_no_digest_module() -> None:
    assert hash_imports(PACKAGE) == []


def test_package_runs_no_global_cli() -> None:
    """The wrapper runs the vendored entry file, never npx or a typedstandards on PATH."""
    for path in PACKAGE.rglob("*.py"):
        if "_vendor" in path.relative_to(PACKAGE).parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "npx" not in text, path
        assert 'which("typedstandards")' not in text, path


# --- each scanner fails on offenders ------------------------------------------------------------

OFFENDERS = {
    "reads_seed.py": "import os\nseed = os.environ.get('TYPEDSTANDARDS_SIGNING_SEED_B64')\n",
    "joined_seed.py": "import os\nseed = os.environ['TYPEDSTANDARDS_SIGNING_' 'SEED_B64']\n",
    "comment_seed.py": "# the CLI reads TYPEDSTANDARDS_SIGNING_SEED_B64\n",
    "env_kw.py": "import subprocess\nsubprocess.run(['node'], env={'A': 'b'})\n",
    "env_star.py": "import subprocess\nsubprocess.run(['node'], **{'env': {}})\n",
    "env_set.py": "import os\nos.environ['X'] = 'y'\n",
    "env_update.py": "import os\nos.environ.update(X='y')\n",
    "env_putenv.py": "import os\nos.putenv('X', 'y')\n",
    "env_execve.py": "import os\nos.execve('/bin/true', ['true'], {})\n",
    "hash_import.py": "import hashlib\n",
    "hash_from.py": "from hashlib import sha256\n",
    "hash_dynamic.py": "import importlib\nh = importlib.import_module('hashlib')\n",
    "hash_hmac.py": "import hmac\n",
    "pin.py": "import hashlib\n",
}


@pytest.fixture
def offenders(tmp_path: Path) -> Path:
    for name, text in OFFENDERS.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def _files(found: list[str]) -> set[str]:
    return {line.split(":", 1)[0] for line in found}


def test_seed_scanner_fails_on_offenders(offenders: Path) -> None:
    assert _files(seed_references(offenders)) == {"reads_seed.py", "joined_seed.py", "comment_seed.py"}


def test_env_scanner_fails_on_offenders(offenders: Path) -> None:
    assert _files(env_overrides(offenders)) == {
        "env_kw.py",
        "env_star.py",
        "env_set.py",
        "env_update.py",
        "env_putenv.py",
        "env_execve.py",
    }


def test_hash_scanner_fails_on_offenders_and_allows_only_pin(offenders: Path) -> None:
    assert _files(hash_imports(offenders)) == {"hash_import.py", "hash_from.py", "hash_dynamic.py", "hash_hmac.py"}
    assert "pin.py" in _files(hash_imports(offenders, allow=frozenset()))


# --- at run time, against the real CLI -----------------------------------------------------------


def _drive_every_command() -> None:
    signed = typedstandards.sign(self_certifying_input())
    withdrawal = typedstandards.withdraw(
        {"targetNodeId": signed["envelopeHash"], "reason": "a test withdrawal", "signer": signed["package"]["signer"]}
    )
    typedstandards.attest(
        {
            "type": "attestation/corroborates/v1",
            "targetNodeId": signed["envelopeHash"],
            "scope": "the whole record",
            "signer": {"bindingTier": "pseudonymous", "displayName": "Example corroborator"},
        }
    )
    bundle = typedstandards.view(signed, visibility="public", attestations=[withdrawal])
    typedstandards.verify(bundle)
    typedstandards.cli_version()


def test_every_child_inherits_the_environment(seed: str, spawned: list[dict[str, Any]]) -> None:
    before = dict(os.environ)
    _drive_every_command()
    entry = str(typedstandards.cli_entry())
    commands = {call["args"][2] for call in spawned if len(call["args"]) > 2 and call["args"][1] == entry}
    assert commands == {"sign", "withdraw", "attest", "view", "verify", "--version"}
    for call in spawned:
        assert "env" not in call["kwargs"], f"env= passed to {call['args']}"
        assert call["environ"] == before, f"the environment changed before {call['args']}"
        assert seed not in " ".join(call["args"]), "the seed reached an argument"
        assert call["stdin"] is None or seed.encode() not in call["stdin"], "the seed reached stdin"
    assert dict(os.environ) == before


class RecordingEnviron(MutableMapping[str, str]):
    """os.environ, recording every key read and any read of the whole mapping."""

    def __init__(self, real: MutableMapping[str, str]) -> None:
        self.real = real
        self.keys_read: list[Any] = []
        self.read_all = False

    def __getitem__(self, key: Any) -> str:
        self.keys_read.append(key)
        return self.real[key]

    def get(self, key: Any, default: Any = None) -> Any:
        self.keys_read.append(key)
        return self.real.get(key, default)

    def __contains__(self, key: object) -> bool:
        self.keys_read.append(key)
        return key in self.real

    def __iter__(self) -> Iterator[str]:
        self.read_all = True
        return iter(self.real)

    def __len__(self) -> int:
        return len(self.real)

    def __setitem__(self, key: str, value: str) -> None:
        self.real[key] = value

    def __delitem__(self, key: str) -> None:
        del self.real[key]

    def copy(self) -> dict[str, str]:
        self.read_all = True
        return dict(self.real)


def test_wrapper_never_reads_the_seed_variable(seed: str, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RecordingEnviron(os.environ)
    monkeypatch.setattr(os, "environ", recorder)
    _drive_every_command()
    assert SEED_VARIABLE not in recorder.keys_read
    assert not recorder.read_all, "the whole environment was read"
