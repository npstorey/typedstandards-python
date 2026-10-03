"""Static scanners for the wrapper's three standing rules (no tests of their own).

- It reads no seed: no module names the CLI's seed variable, in any form.
- It passes the child process no environment but the inherited one: no ``env=`` on any call,
  and nothing that sets, unsets or replaces a variable for a child.
- It computes none of the format's hashes: no module imports ``hashlib`` (or the modules behind
  it), except the allowlisted P2 ``pin`` module, whose digest is a signed assertion.

Each scanner takes a directory and returns one line per offence, so a test can drive it over the
package and over a fixture tree of offenders.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

SEED_VARIABLE = "TYPEDSTANDARDS_SIGNING_SEED_B64"

#: Modules that compute digests. ``hmac`` and the underscore modules are hashlib's back doors.
HASH_MODULES = frozenset(
    {"hashlib", "_hashlib", "_sha1", "_sha2", "_sha256", "_sha512", "_sha3", "_md5", "_blake2", "hmac"}
)

#: The one module allowed to import hashlib: P2's pin (it does not exist yet), relative to the
#: package directory.
HASH_ALLOWLIST = frozenset({"pin.py"})

#: Calls that start a process with an explicit environment, or change this process's.
ENV_CALLS = frozenset(
    {
        "putenv",
        "unsetenv",
        "execve",
        "execle",
        "execlpe",
        "execvpe",
        "spawnve",
        "spawnle",
        "spawnlpe",
        "spawnvpe",
        "posix_spawn",
        "posix_spawnp",
    }
)
ENVIRON_MUTATORS = frozenset({"update", "pop", "popitem", "setdefault", "clear", "__setitem__", "__delitem__"})


def python_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        if "_vendor" not in path.relative_to(root).parts:
            yield path


def _is_environ(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ"
    )


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def seed_references(root: Path) -> list[str]:
    """Every line of every module that names the seed variable: code, string or comment."""
    found = []
    for path in python_files(root):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SEED_VARIABLE in line:
                found.append(f"{path.relative_to(root)}:{number}: names {SEED_VARIABLE}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # A name split across string literals that join at compile time is still one constant.
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and SEED_VARIABLE in node.value:
                entry = f"{path.relative_to(root)}:{node.lineno}: a string holds {SEED_VARIABLE}"
                if not any(f.startswith(f"{path.relative_to(root)}:{node.lineno}:") for f in found):
                    found.append(entry)
    return found


def env_overrides(root: Path) -> list[str]:
    """Every call that passes ``env=``, and every change to the process environment."""
    found = []
    for path in python_files(root):
        where = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "env":
                        found.append(f"{where}:{node.lineno}: a call passes env=")
                    elif (
                        keyword.arg is None
                        and isinstance(keyword.value, ast.Dict)
                        and any(isinstance(k, ast.Constant) and k.value == "env" for k in keyword.value.keys)
                    ):
                        found.append(f"{where}:{node.lineno}: a call passes env= through **")
                name = _call_name(node)
                if name in ENV_CALLS:
                    found.append(f"{where}:{node.lineno}: calls {name}")
                if name in ENVIRON_MUTATORS and isinstance(node.func, ast.Attribute) and _is_environ(node.func.value):
                    found.append(f"{where}:{node.lineno}: changes os.environ ({name})")
            targets: list[ast.AST] = []
            if isinstance(node, (ast.Assign, ast.Delete)):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and _is_environ(target.value):
                    found.append(f"{where}:{node.lineno}: changes os.environ (item)")
                elif isinstance(target, ast.Attribute) and target.attr == "environ":
                    found.append(f"{where}:{node.lineno}: replaces os.environ")
    return found


def hash_imports(root: Path, allow: frozenset[str] = HASH_ALLOWLIST) -> list[str]:
    """Every import of a digest module outside the allowlist, static or dynamic."""
    found = []
    for path in python_files(root):
        where = path.relative_to(root)
        if where.as_posix() in allow:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Call) and _call_name(node) in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    modules = [first.value]
            for module in modules:
                if module.split(".")[0] in HASH_MODULES:
                    found.append(f"{where}:{node.lineno}: imports {module}")
    return found
