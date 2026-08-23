"""What each external task topic actually does.

Handlers are plain functions: decoded process variables in, result variables
out. They know nothing about HTTP, which is what makes them easy to test. The
shell runner is injected so a test can replay canned results instead of
starting real processes.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devflows_core.config import ConfigError, DevflowsConfig, load_config
from devflows_core.steps import StepResult, run_step
from devflows_core.versions import classify_release

GATES_TOPIC = "devflows.gates"
NOTES_TOPIC = "devflows.notes"
TAG_TOPIC = "devflows.tag"
PUBLISH_TOPIC = "devflows.publish"
UNTAG_TOPIC = "devflows.untag"

# Raised as a BPMN error so the process can compensate rather than sit on an
# incident. The code has to match the errorCode in processes/release.bpmn.
PUBLISH_FAILED = "PUBLISH_FAILED"

DEFAULT_APPROVAL_TIMEOUT = "PT24H"

NOTES_TIMEOUT_SECONDS = 120
COMMIT_LOG_LIMIT = 50

_URL_PATTERN = re.compile(r"https://\S+")


class HandlerError(Exception):
    """The work failed, but trying again might succeed.

    Think of a network blip, a command that could not start, or gh not being
    logged in. The worker reports this to the engine as an external task
    failure with retries left, so the engine hands the task back after a delay.
    """

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BusinessError(Exception):
    """The work will not succeed, and the process should decide what to do.

    This is not a broken worker, so it is not an incident. The worker raises it
    to the engine as a BPMN error, which an error boundary event catches. The
    publish step uses it so that a release that cannot be published compensates
    and removes its own tag.
    """

    def __init__(self, code: str, message: str, details: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def handle_gates(
    variables: dict[str, Any],
    *,
    runner: Callable[..., StepResult] = run_step,
) -> dict[str, Any]:
    """Run every gate in order and stop at the first failure."""
    repo, config = _repo_and_config(variables)

    report: list[dict[str, Any]] = []
    passed = True
    for gate in config.gates:
        result = runner(gate.run, cwd=repo)
        report.append(
            {
                "name": gate.name,
                "command": gate.run,
                "exit_code": result.exit_code,
                "passed": result.ok,
                "duration_seconds": round(result.duration_seconds, 2),
                "timed_out": result.timed_out,
                "output": result.output,
            }
        )
        if not result.ok:
            passed = False
            break

    return {
        "gates_passed": passed,
        "gates_report": json.dumps(report, indent=2),
        # The approval timer needs this variable to exist. Defaulting it here
        # means a run started with plain curl still gets a timer.
        "approval_timeout": variables.get("approval_timeout") or DEFAULT_APPROVAL_TIMEOUT,
    }


def handle_notes(
    variables: dict[str, Any],
    *,
    runner: Callable[..., StepResult] = run_step,
) -> dict[str, Any]:
    """Draft the release notes and say how big this release is.

    Drafting is best effort on purpose: a missing or unhappy claude CLI must
    never fail a release, so every failure here lands in the commit list
    fallback instead of an exception.
    """
    repo, config = _repo_and_config(variables)
    version = _required(variables, "version")

    previous_version = _newest_tag(repo, runner)
    release_kind = classify_release(previous_version, version)
    commits = _commits_since(repo, previous_version, runner)

    notes = _draft_notes_with_claude(repo, version, release_kind, commits, runner)
    source = "claude"
    if not notes:
        notes = _notes_from_commits(config.tag.format.format(version=version), commits)
        source = "git-log"

    return {
        "release_notes": notes,
        "notes_source": source,
        "previous_version": previous_version or "",
        "release_kind": release_kind,
    }


def handle_tag(
    variables: dict[str, Any],
    *,
    runner: Callable[..., StepResult] = run_step,
) -> dict[str, Any]:
    """Create the release tag, or report the tag a real run would create."""
    repo, config = _repo_and_config(variables)
    version = _required(variables, "version")
    dry_run = bool(variables.get("dry_run", False))

    tag_name = config.tag.format.format(version=version)
    if dry_run:
        return {"tag_name": tag_name, "tag_created": False, "dry_run": True}

    command = f'git tag -a {tag_name} -m "Release {tag_name}"'
    result = runner(command, cwd=repo)
    if not result.ok:
        raise HandlerError(f"Could not create tag {tag_name}: {result.output}", result.output)

    return {"tag_name": tag_name, "tag_created": True, "dry_run": False}


def handle_publish(
    variables: dict[str, Any],
    *,
    runner: Callable[..., StepResult] = run_step,
) -> dict[str, Any]:
    """Push the tag and create the GitHub Release.

    The two failure modes are deliberately different. A missing gh login is a
    HandlerError, because logging in and retrying works. A push or a release
    that the tools reject is a BusinessError, because retrying will not help;
    the process catches it and compensates by removing the tag.
    """
    repo, config = _repo_and_config(variables)
    version = _required(variables, "version")
    dry_run = bool(variables.get("dry_run", False))
    tag_name = variables.get("tag_name") or config.tag.format.format(version=version)

    notes_file = _notes_file(config.publish.run, variables, tag_name)
    publish_command = config.publish.run.format(version=version, notes_file=notes_file or "")

    if dry_run:
        return {
            "release_url": f"(dry run) would publish {tag_name}",
            "published": False,
            "publish_command": publish_command,
            "dry_run": True,
        }

    auth = runner("gh auth status", cwd=repo)
    if not auth.ok:
        raise HandlerError(
            "gh is not authenticated. Run 'gh auth login' and start the release again.",
            auth.output,
        )

    push = runner(f"git push origin {tag_name}", cwd=repo)
    if not push.ok:
        raise BusinessError(
            PUBLISH_FAILED, f"Could not push tag {tag_name}: {push.output}", push.output
        )

    release = runner(publish_command, cwd=repo)
    if not release.ok:
        raise BusinessError(PUBLISH_FAILED, f"Publishing failed: {release.output}", release.output)

    match = _URL_PATTERN.search(release.output)
    return {
        "release_url": match.group(0) if match else "",
        "published": True,
        "publish_command": publish_command,
        "dry_run": False,
    }


def handle_untag(
    variables: dict[str, Any],
    *,
    runner: Callable[..., StepResult] = run_step,
) -> dict[str, Any]:
    """Undo the tag step. Only ever reached through BPMN compensation.

    A release that could not be published must not leave a tag behind, locally
    or on the remote. Neither delete is allowed to fail the compensation: if the
    tag was never pushed, deleting it remotely fails, and that is fine.
    """
    repo, config = _repo_and_config(variables)
    version = _required(variables, "version")
    tag_name = variables.get("tag_name") or config.tag.format.format(version=version)
    dry_run = bool(variables.get("dry_run", False))

    if dry_run:
        return {"tag_deleted": False, "untag_detail": f"(dry run) would delete {tag_name}"}

    local = runner(f"git tag -d {tag_name}", cwd=repo)
    remote = runner(f"git push origin :refs/tags/{tag_name}", cwd=repo)

    detail = f"local: {'deleted' if local.ok else 'not deleted'}, "
    detail += f"remote: {'deleted' if remote.ok else 'not deleted'}"
    return {"tag_deleted": local.ok, "untag_detail": detail}


HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    GATES_TOPIC: handle_gates,
    NOTES_TOPIC: handle_notes,
    TAG_TOPIC: handle_tag,
    PUBLISH_TOPIC: handle_publish,
    UNTAG_TOPIC: handle_untag,
}


def _newest_tag(repo: Path, runner: Callable[..., StepResult]) -> str | None:
    """The newest existing tag, or None. A repository without tags is normal."""
    result = runner("git tag --list --sort=-v:refname", cwd=repo)
    if not result.ok:
        return None
    for line in result.output.splitlines():
        if line.strip():
            return line.strip()
    return None


def _commits_since(
    repo: Path,
    previous_version: str | None,
    runner: Callable[..., StepResult],
) -> list[str]:
    """One line per commit that belongs to this release."""
    if previous_version:
        command = f"git log {previous_version}..HEAD --oneline --no-decorate"
    else:
        command = f"git log --oneline --no-decorate -n {COMMIT_LOG_LIMIT}"

    result = runner(command, cwd=repo)
    if not result.ok:
        return []
    return [line.strip() for line in result.output.splitlines() if line.strip()]


def _draft_notes_with_claude(
    repo: Path,
    version: str,
    release_kind: str,
    commits: list[str],
    runner: Callable[..., StepResult],
) -> str:
    """Ask the local claude CLI for notes, or return "" if that did not work."""
    prompt = _notes_prompt(version, release_kind, commits)
    # The prompt goes on stdin, never on the command line. Commit messages are
    # arbitrary text, and shell quoting is not portable: shlex.quote produces
    # POSIX single quotes, which cmd.exe treats as ordinary characters, so on
    # Windows the prompt arrives shredded into fragments.
    try:
        result = runner("claude -p", cwd=repo, timeout=NOTES_TIMEOUT_SECONDS, stdin=prompt)
    except Exception:
        # Whatever went wrong, notes are not worth failing a release over.
        return ""
    return _strip_code_fence(result.output) if result.ok else ""


def _strip_code_fence(text: str) -> str:
    """Return just the notes when the model wrapped them in a code fence.

    Asking for "the notes only" does not reliably stop a model from opening
    with ```markdown, and some also add a line of chatter after the closing
    fence. Published as-is, both would end up in the release body.

    The rule is deliberately narrow: only a fence on the first non-empty line
    counts as a wrapper. Notes that legitimately contain a fenced command block
    further down keep it.
    """
    lines = text.strip().splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None or not lines[first].lstrip().startswith("```"):
        return text.strip()

    body = []
    for line in lines[first + 1 :]:
        if line.strip() == "```":
            break
        body.append(line)
    return "\n".join(body).strip()


def _notes_prompt(version: str, release_kind: str, commits: list[str]) -> str:
    """The instruction sent to the claude CLI."""
    listing = "\n".join(f"- {commit}" for commit in commits) or "- (no commits found)"
    return (
        f"Write the release notes for version {version} of this repository. "
        f"Compared with the previous release this is a {release_kind} release.\n\n"
        "Keep it short, use markdown, group the entries by kind of change, and "
        "answer with the notes only: no preamble, no closing remark, and do not "
        "wrap the answer in a code fence.\n\n"
        f"Commits in this release:\n{listing}\n"
    )


def _notes_from_commits(tag_name: str, commits: list[str]) -> str:
    """The fallback notes: the commit list, or a single line when there is none."""
    if not commits:
        return f"Release {tag_name}."
    bullets = "\n".join(f"- {commit}" for commit in commits)
    return f"## Changes\n\n{bullets}"


def _notes_file(publish_command: str, variables: dict[str, Any], tag_name: str) -> str | None:
    """Write the approved release notes to a file, if the command asks for one.

    Only repositories whose publish command contains {notes_file} pay for this.
    The file is left on disk for the command to read; the operating system
    cleans up its own temporary directory.
    """
    if "{notes_file}" not in publish_command:
        return None

    notes = str(variables.get("release_notes") or "").strip() or f"Release {tag_name}."
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", prefix="devflows-notes-", delete=False, encoding="utf-8"
    )
    with handle as target:
        target.write(notes + "\n")
    return handle.name


def _repo_and_config(variables: dict[str, Any]) -> tuple[Path, DevflowsConfig]:
    repo = Path(_required(variables, "repo_path"))
    try:
        return repo, load_config(repo)
    except ConfigError as error:
        raise HandlerError(str(error)) from error


def _required(variables: dict[str, Any], name: str) -> str:
    value = variables.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise HandlerError(f"The process variable '{name}' is missing or empty")
    return str(value)
