"""Fixtures: a test seed in the environment, and a recorder of the wrapper's child processes."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest
from support import SEED_VARIABLE, fresh_seed_b64


@pytest.fixture
def seed(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a fresh seed in the environment the wrapper's child inherits."""
    value = fresh_seed_b64()
    monkeypatch.setenv(SEED_VARIABLE, value)
    return value


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every child process the wrapper starts: its argv, its keyword arguments, the
    stdin bytes it was given, and os.environ at that moment. The call still runs."""
    calls: list[dict[str, Any]] = []
    real_popen = subprocess.Popen
    real_communicate = subprocess.Popen.communicate

    class RecordingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            self._record = {"args": list(args), "kwargs": dict(kwargs), "environ": dict(os.environ), "stdin": None}
            calls.append(self._record)
            super().__init__(args, *rest, **kwargs)

        def communicate(self, input: Any = None, timeout: Any = None) -> Any:
            self._record["stdin"] = input
            return real_communicate(self, input, timeout)

    monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
    return calls
