"""The devflows tools as plain functions.

Each one takes an engine client, returns a plain dictionary and never raises.
The caller is a language model that has to explain what happened to a human, so
a readable 'error' string is worth more than a stack trace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devflows_core.config import ConfigError, load_config
from devflows_core.engine import PROCESS_KEY, EngineError
from devflows_core.paths import BpmnNotFound, default_bpmn_path

DECISION_KEY = "release-policy"

# The CIB seven web UI. The older webapps under /camunda/app/ still work in 2.2
# but render a "deprecated and no longer supported" banner, so do not link there.
INSTANCE_URL = "http://localhost:8080/webapp/#/seven/auth/processes/instance/{instance_id}"


def engine_status(client: Any) -> dict[str, Any]:
    """Is the engine up, and which version is it?"""
    status = client.engine_status()
    return {
        "ok": bool(status["reachable"]),
        "url": status["url"],
        "version": status["version"],
        "engines": status["engines"],
        "error": status["error"],
    }


def deploy_process(client: Any, bpmn_path: str | None = None) -> dict[str, Any]:
    """Deploy the release process. Deploying the same file twice is harmless."""
    try:
        path = Path(bpmn_path) if bpmn_path else default_bpmn_path()
    except BpmnNotFound as error:
        return _failure(str(error))

    try:
        result = client.deploy(path)
    except EngineError as error:
        return _failure(str(error))

    return {
        "ok": True,
        "deployment_id": result["deployment_id"],
        "process_definition_keys": result["process_definition_keys"],
        "bpmn_path": str(path),
    }


def list_processes(client: Any) -> dict[str, Any]:
    """Which process definitions does the engine know about?"""
    try:
        definitions = client.list_process_definitions()
    except EngineError as error:
        return _failure(str(error))
    return {"ok": True, "process_definitions": definitions}


def start_release(
    client: Any,
    repo_path: str,
    version: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Start a release run. Defaults to a dry run, because that is the safe default."""
    if not version or not version.strip():
        return _failure("A version is required, for example '0.1.0'")

    try:
        load_config(repo_path)
    except ConfigError as error:
        return _failure(str(error))

    variables = {
        "repo_path": str(repo_path),
        "version": version.strip(),
        "dry_run": bool(dry_run),
    }
    try:
        instance_id = client.start_process(PROCESS_KEY, variables)
    except EngineError as error:
        return _failure(str(error))

    return {
        "ok": True,
        "process_instance_id": instance_id,
        "dry_run": bool(dry_run),
        "version": version.strip(),
        "repo_path": str(repo_path),
        "instance_url": INSTANCE_URL.format(instance_id=instance_id),
    }


def get_run(client: Any, process_instance_id: str) -> dict[str, Any]:
    """What is this release run doing, and what has it produced so far?"""
    try:
        running = client.get_process_instance(process_instance_id)
        if running is not None:
            variables = client.get_variables(process_instance_id)
            state = "running"
            activities = client.get_active_activity_names(process_instance_id)
            tasks = client.list_tasks(process_instance_id)
        else:
            historic = client.get_historic_process_instance(process_instance_id)
            if historic is None:
                return _failure(f"No process instance with id {process_instance_id}")
            variables = client.get_historic_variables(process_instance_id)
            state = historic.get("state", "COMPLETED")
            activities = []
            tasks = []
        incidents = client.list_incidents(process_instance_id)
    except EngineError as error:
        return _failure(str(error))

    return {
        "ok": True,
        "process_instance_id": process_instance_id,
        "state": state,
        "active_activities": activities,
        "open_tasks": tasks,
        # A run that is not moving usually has an incident behind it, so say so
        # here rather than making the caller go looking.
        "incidents": incidents,
        "variables": variables,
        "gates": _decode_gate_report(variables.get("gates_report")),
    }


def list_gates(repo_path: str) -> dict[str, Any]:
    """What would a release of this repository run? No engine involved."""
    try:
        config = load_config(repo_path)
    except ConfigError as error:
        return _failure(str(error))

    return {
        "ok": True,
        "repo_path": str(repo_path),
        "gates": [{"name": gate.name, "run": gate.run} for gate in config.gates],
        "tag_format": config.tag.format,
        "publish_command": config.publish.run,
    }


def approve_gate(
    client: Any,
    task_id: str,
    approve: bool,
    comment: str = "",
) -> dict[str, Any]:
    """Complete the approval user task. This is the human decision."""
    try:
        client.complete_task(
            task_id, {"approved": bool(approve), "approval_comment": comment or ""}
        )
    except EngineError as error:
        return _failure(str(error))

    return {"ok": True, "task_id": task_id, "approved": bool(approve), "comment": comment or ""}


def list_runs(client: Any, limit: int = 10) -> dict[str, Any]:
    """The most recent release runs, newest first."""
    try:
        runs = client.list_historic_process_instances(PROCESS_KEY, limit)
    except EngineError as error:
        return _failure(str(error))
    return {"ok": True, "runs": runs}


def retry_run(client: Any, process_instance_id: str) -> dict[str, Any]:
    """Give a stuck run another attempt.

    An incident on an external task holds the task and its retry count at zero.
    Setting the retries back above zero clears the incident and puts the task
    back in the queue, which is what a person would do in Cockpit.
    """
    try:
        incidents = client.list_incidents(process_instance_id)
    except EngineError as error:
        return _failure(str(error))

    retried = []
    for incident in incidents:
        task_id = incident.get("configuration")
        if incident.get("type") != "failedExternalTask" or not task_id:
            continue
        try:
            client.set_external_task_retries(task_id, 1)
        except EngineError as error:
            return _failure(str(error))
        retried.append(task_id)

    if not retried:
        return _failure(
            f"Nothing to retry on {process_instance_id}: no failed external task incident"
        )
    return {"ok": True, "process_instance_id": process_instance_id, "retried_tasks": retried}


def cancel_run(
    client: Any,
    process_instance_id: str,
    reason: str = "cancelled through the devflows MCP server",
) -> dict[str, Any]:
    """Stop a running release. The reason is kept in the history."""
    try:
        client.delete_process_instance(process_instance_id, reason)
    except EngineError as error:
        return _failure(str(error))
    return {"ok": True, "process_instance_id": process_instance_id, "reason": reason}


def doctor(client: Any, repo_path: str | None = None) -> dict[str, Any]:
    """Check everything a release needs, and say what is missing.

    Every check reports rather than raises, because the point of this tool is
    to answer "why will this not run" in one call.
    """
    checks: list[dict[str, Any]] = []

    status = client.engine_status()
    engine_detail = status["error"] or f"CIB seven {status['version']}"
    _check(checks, "engine", status["reachable"], engine_detail)

    definitions: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    if status["reachable"]:
        try:
            definitions = client.list_process_definitions()
            decisions = client.list_decision_definitions()
        except EngineError as error:
            _check(checks, "deployments", False, str(error))

    keys = {item.get("key") for item in definitions}
    _check(
        checks,
        "process deployed",
        PROCESS_KEY in keys,
        f"{PROCESS_KEY} found" if PROCESS_KEY in keys else f"deploy {PROCESS_KEY} first",
    )

    decision_keys = {item.get("key") for item in decisions}
    _check(
        checks,
        "decision deployed",
        DECISION_KEY in decision_keys,
        f"{DECISION_KEY} found"
        if DECISION_KEY in decision_keys
        else f"deploy {DECISION_KEY} first",
    )

    if repo_path:
        config = list_gates(repo_path)
        _check(
            checks,
            "devflows.yaml",
            config["ok"],
            config.get("error") or f"{len(config.get('gates', []))} gate(s)",
        )

    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }


def _check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def _failure(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _decode_gate_report(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return report if isinstance(report, list) else []
