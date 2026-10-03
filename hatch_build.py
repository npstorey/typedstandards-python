"""Vendor @typedstandards/cli into the wheel (G0 D1 = A).

At every wheel build, standard or editable, this hook copies ``package.json`` and
``package-lock.json`` into ``src/typedstandards/_vendor/`` and runs
``npm ci --omit=dev --ignore-scripts`` there. The resulting ``node_modules`` tree, with
each package's own licence file, ships inside the wheel, so an installed wheel needs Node
and nothing from npm. An editable install (``uv sync``) runs the same hook, so tests drive
the same tree a user gets.

Building needs ``npm`` on ``PATH`` and the npm registry; installing the wheel needs neither.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

VENDOR = Path("src") / "typedstandards" / "_vendor"
LICENCE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "LICENCE.txt")


class VendorCliHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return
        root = Path(self.root)
        vendor = root / VENDOR
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "building typedstandards needs npm on PATH: the build vendors @typedstandards/cli "
                "with `npm ci --omit=dev --ignore-scripts` (installing the built wheel does not)"
            )
        if vendor.exists():
            shutil.rmtree(vendor)
        vendor.mkdir(parents=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(root / name, vendor / name)
        self.app.display_info(f"vendoring @typedstandards/cli: npm ci --omit=dev --ignore-scripts in {VENDOR}")
        subprocess.run(
            [npm, "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=vendor,
            check=True,
        )
        modules = vendor / "node_modules"
        # npm's .bin holds symlinks, which a wheel cannot carry; the wrapper runs the CLI's
        # entry file with node, never through .bin.
        shutil.rmtree(modules / ".bin", ignore_errors=True)
        lock = json.loads((vendor / "package-lock.json").read_text(encoding="utf-8"))
        for key in lock["packages"]:
            if not key:
                continue
            package_dir = vendor / key
            if not any((package_dir / name).is_file() for name in LICENCE_NAMES):
                raise RuntimeError(f"{key} ships no licence file; the wheel must carry each vendored package's licence")
