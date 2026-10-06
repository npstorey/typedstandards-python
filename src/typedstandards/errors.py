"""The exceptions the wrapper raises.

The CLI's exit codes 1 to 4 (``packages/cli/src/errors.ts`` in typedstandards) map to the
four subclasses of :class:`CliError`, each carrying the exit code and the CLI's stderr text.
A missing or too-old Node is a :class:`NodeLocatorError`, raised before the CLI runs.
``publish`` and ``publish_attestation`` raise :class:`PublishError`, and
:class:`PublishRefusedError` for a refusal made before any write.
"""

from __future__ import annotations

from typing import Any


class NodeLocatorError(RuntimeError):
    """No usable Node binary: none was found, or the one found is below the CLI's floor."""


class CliNotVendoredError(RuntimeError):
    """The vendored CLI is missing from the installed package."""


class CliError(Exception):
    """The CLI exited with a code other than 0.

    ``exit_code`` is the CLI's exit code, ``stderr`` its standard error as text, and
    ``command`` the CLI command that ran.
    """

    def __init__(self, exit_code: int, stderr: str, command: str) -> None:
        self.exit_code = exit_code
        self.stderr = stderr
        self.command = command
        detail = stderr.strip() or "(nothing on stderr)"
        super().__init__(f"typedstandards {command} exited {exit_code}: {detail}")


class VerificationError(CliError):
    """Exit 1: a record, or the CLI's own result, did not verify.

    ``document`` is what the CLI printed on stdout, parsed: ``verify`` prints its
    ``{ok: false, ...}`` verdict; ``sign``, ``withdraw`` and ``attest`` print nothing, so it is
    ``None`` for them.
    """

    def __init__(self, exit_code: int, stderr: str, command: str, document: Any = None) -> None:
        super().__init__(exit_code, stderr, command)
        self.document = document


class UsageError(CliError):
    """Exit 2: an argument or an input is wrong."""


class SeedError(CliError):
    """Exit 3: the signing seed's environment variable is missing or malformed."""


class InternalError(CliError):
    """Exit 4: an internal error in the CLI."""


class PublishError(RuntimeError):
    """``publish`` or ``publish_attestation`` did not complete: the GitHub API answered with an
    error, or the branch moved again after the one retry. The message names the request and
    GitHub's own message, never a credential."""


class PublishRefusedError(PublishError):
    """``publish`` or ``publish_attestation`` refused the call before any write request: the
    token, the name, the title, the record, the role or the host's files did not pass a check."""
