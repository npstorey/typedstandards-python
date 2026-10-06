"""``publish`` and ``publish_attestation``: write a signed record, or an attestation on one, to a
GitHub Pages host made from the host template's publish mode. (Typed stub: not implemented.)"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

#: The environment variable the token is read from when no ``token=`` is given.
TOKEN_VARIABLE = "TYPEDSTANDARDS_GITHUB_TOKEN"


class GitHubPagesHost:
    """A GitHub repository whose Pages site a publish-mode workflow builds from ``host.json``."""

    def __init__(
        self,
        repository: str,
        *,
        branch: str = "main",
        token: str | None = None,
        api_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        raise NotImplementedError


def publish(
    signed: Mapping[str, Any] | str | os.PathLike[str],
    *,
    host: GitHubPagesHost,
    title: str,
    name: str | None = None,
    notebook: str | os.PathLike[str] | None = None,
    role: str = "notebook",
    revises: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raise NotImplementedError


def publish_attestation(
    node: Mapping[str, Any] | str | os.PathLike[str], *, host: GitHubPagesHost, name: str
) -> dict[str, Any]:
    raise NotImplementedError
