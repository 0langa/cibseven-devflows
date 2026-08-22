"""The seven devflows tools as plain functions.

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

COCKPIT_INSTANCE_URL = (
    "http://localhost:8080/camunda/app/cockpit/default/#/process-instance/{instance_id}"
)


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
        "cockpit_url": COCKPIT_INSTANCE_URL.format(instance_id=instance_id),
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
    except EngineError as error:
        return _failure(str(error))

    return {
        "ok": True,
        "process_instance_id": process_instance_id,
        "state": state,
        "active_activities": activities,
        "open_tasks": tasks,
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
