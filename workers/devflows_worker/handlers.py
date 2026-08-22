"""What each external task topic actually does.

Handlers are plain functions: decoded process variables in, result variables
out. They know nothing about HTTP, which is what makes them easy to test. The
shell runner is injected so a test can replay canned results instead of
starting real processes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devflows_core.config import ConfigError, DevflowsConfig, load_config
from devflows_core.steps import StepResult, run_step

GATES_TOPIC = "devflows.gates"
TAG_TOPIC = "devflows.tag"
PUBLISH_TOPIC = "devflows.publish"

_URL_PATTERN = re.compile(r"https://\S+")


class HandlerError(Exception):
    """A handler could not do its job. The message goes back to the engine."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
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
    """Push the tag and create the GitHub Release."""
    repo, config = _repo_and_config(variables)
    version = _required(variables, "version")
    dry_run = bool(variables.get("dry_run", False))
    tag_name = variables.get("tag_name") or config.tag.format.format(version=version)
    publish_command = config.publish.run.format(version=version)

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
        raise HandlerError(f"Could not push tag {tag_name}: {push.output}", push.output)

    release = runner(publish_command, cwd=repo)
    if not release.ok:
        raise HandlerError(f"Publishing failed: {release.output}", release.output)

    match = _URL_PATTERN.search(release.output)
    return {
        "release_url": match.group(0) if match else "",
        "published": True,
        "publish_command": publish_command,
        "dry_run": False,
    }


HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    GATES_TOPIC: handle_gates,
    TAG_TOPIC: handle_tag,
    PUBLISH_TOPIC: handle_publish,
}


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
