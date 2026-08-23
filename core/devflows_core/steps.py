"""Run one shell command from devflows.yaml and report the result.

The commands come from the repository being released, they run as the
developer, on the developer's machine, in that repository's directory. That is
the whole point: the engine holds the state, the machine does the work.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class StepResult:
    """What happened when one command ran."""

    command: str
    exit_code: int
    output: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """True only when the command finished and reported success."""
        return self.exit_code == 0 and not self.timed_out


def trim_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Shorten long output, keeping the beginning and the end.

    Process variables live in the engine database. A chatty test run must not
    be allowed to fill it, but the first and last lines are usually the ones
    that explain a failure, so both ends are kept.
    """
    if len(text) <= limit:
        return text
    half = limit // 2
    removed = len(text) - 2 * half
    return f"{text[:half]}\n... [{removed} characters trimmed] ...\n{text[-half:]}"


def run_step(
    command: str,
    cwd: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    stdin: str | None = None,
) -> StepResult:
    """Run a shell command in a directory and capture everything it printed.

    Pass anything long or awkward through `stdin` rather than building it into
    the command. Quoting rules differ between shells - POSIX quoting means
    nothing to cmd.exe - so text with spaces, quotes or newlines in a command
    string is silently mangled on one platform or the other.
    """
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            input=stdin,
        )
    except subprocess.TimeoutExpired as expired:
        duration = time.monotonic() - started
        partial = _merge(expired.stdout, expired.stderr)
        return StepResult(
            command=command,
            exit_code=124,
            output=trim_output(f"{partial}\nCommand timed out after {timeout} seconds."),
            duration_seconds=duration,
            timed_out=True,
        )

    duration = time.monotonic() - started
    return StepResult(
        command=command,
        exit_code=completed.returncode,
        output=trim_output(_merge(completed.stdout, completed.stderr)),
        duration_seconds=duration,
    )


def _merge(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    """Join captured stdout and stderr into one readable block."""
    parts = []
    for stream in (stdout, stderr):
        if not stream:
            continue
        text = stream.decode("utf-8", "replace") if isinstance(stream, bytes) else stream
        text = text.strip()
        if text:
            parts.append(text)
    return "\n".join(parts)
