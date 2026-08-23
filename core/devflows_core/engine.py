"""A small REST client for the CIB seven / Camunda 7 engine.

Only the calls this project actually makes are implemented. Every response is
reduced to plain Python before it leaves this module, so neither the worker nor
the MCP server has to know what the engine JSON looks like.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from devflows_core.variables import from_engine, to_engine

DEFAULT_ENGINE_URL = "http://localhost:8080/engine-rest"
PROCESS_KEY = "devflows-release"


class EngineError(RuntimeError):
    """The engine refused a request or could not be reached."""


class EngineClient:
    """Talks to one engine over HTTP."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        configured = base_url or os.environ.get("DEVFLOWS_ENGINE_URL") or DEFAULT_ENGINE_URL
        self.base_url = configured.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, transport=transport, timeout=timeout)

    def __enter__(self) -> EngineClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ---- status ---------------------------------------------------------

    def engine_status(self) -> dict[str, Any]:
        """Check that the engine answers, and report its version."""
        try:
            version = self._request("GET", "/version")
            engines = self._request("GET", "/engine")
        except EngineError as error:
            return {
                "reachable": False,
                "version": None,
                "engines": [],
                "url": self.base_url,
                "error": str(error),
            }
        return {
            "reachable": True,
            "version": version.get("version"),
            "engines": [engine.get("name") for engine in engines],
            "url": self.base_url,
            "error": None,
        }

    # ---- deployment and definitions -------------------------------------

    def deploy(self, bpmn_path: Path) -> dict[str, Any]:
        """Deploy one BPMN file and report what was deployed."""
        path = Path(bpmn_path)
        if not path.is_file():
            raise EngineError(f"BPMN file does not exist: {path}")

        files = {path.name: (path.name, path.read_bytes(), "application/octet-stream")}
        data = {
            "deployment-name": "cibseven-devflows",
            "deploy-changed-only": "true",
            "deployment-source": "cibseven-devflows",
        }
        payload = self._request("POST", "/deployment/create", data=data, files=files)
        deployed = payload.get("deployedProcessDefinitions") or {}
        return {
            "deployment_id": payload.get("id"),
            "process_definition_keys": [definition.get("key") for definition in deployed.values()],
        }

    def list_process_definitions(self) -> list[dict[str, Any]]:
        """List deployed process definitions."""
        payload = self._request("GET", "/process-definition")
        return [
            {
                "key": item.get("key"),
                "id": item.get("id"),
                "version": item.get("version"),
                "name": item.get("name"),
            }
            for item in payload
        ]

    # ---- instances -------------------------------------------------------

    def start_process(self, key: str, variables: dict[str, Any]) -> str:
        """Start a process instance by definition key and return its id."""
        payload = self._request(
            "POST",
            f"/process-definition/key/{key}/start",
            json={"variables": to_engine(variables)},
        )
        return payload["id"]

    def get_process_instance(self, process_instance_id: str) -> dict[str, Any] | None:
        """The running instance, or None once it has finished."""
        return self._optional("GET", f"/process-instance/{process_instance_id}")

    def get_historic_process_instance(self, process_instance_id: str) -> dict[str, Any] | None:
        """The historic record of an instance, running or finished."""
        return self._optional("GET", f"/history/process-instance/{process_instance_id}")

    def get_variables(self, process_instance_id: str) -> dict[str, Any]:
        """Variables of a running instance."""
        payload = self._request(
            "GET",
            f"/process-instance/{process_instance_id}/variables",
            params={"deserializeValues": "false"},
        )
        return from_engine(payload)

    def get_historic_variables(self, process_instance_id: str) -> dict[str, Any]:
        """Variables of a finished instance, read from history."""
        payload = self._request(
            "GET",
            "/history/variable-instance",
            params={"processInstanceId": process_instance_id, "deserializeValues": "false"},
        )
        return {item["name"]: item.get("value") for item in payload}

    def get_active_activity_names(self, process_instance_id: str) -> list[str]:
        """Names of the activities the instance is currently waiting in."""
        tree = self._optional("GET", f"/process-instance/{process_instance_id}/activity-instances")
        if tree is None:
            return []
        names: list[str] = []
        _collect_activity_names(tree, names)
        return names

    # ---- user tasks ------------------------------------------------------

    def list_tasks(self, process_instance_id: str | None = None) -> list[dict[str, Any]]:
        """Open user tasks, optionally limited to one process instance."""
        params = {"processInstanceId": process_instance_id} if process_instance_id else {}
        payload = self._request("GET", "/task", params=params)
        return [
            {
                "id": task.get("id"),
                "name": task.get("name"),
                "assignee": task.get("assignee"),
                "process_instance_id": task.get("processInstanceId"),
                "created": task.get("created"),
            }
            for task in payload
        ]

    def complete_task(self, task_id: str, variables: dict[str, Any]) -> None:
        """Complete a user task with the given variables."""
        self._request("POST", f"/task/{task_id}/complete", json={"variables": to_engine(variables)})

    # ---- runs and incidents ----------------------------------------------

    def list_historic_process_instances(
        self, process_definition_key: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """The most recently started instances of one process, newest first."""
        payload = self._request(
            "GET",
            "/history/process-instance",
            params={
                "processDefinitionKey": process_definition_key,
                "sortBy": "startTime",
                "sortOrder": "desc",
                "maxResults": limit,
            },
        )
        return [
            {
                "process_instance_id": item.get("id"),
                "state": item.get("state"),
                "start_time": item.get("startTime"),
                "end_time": item.get("endTime"),
            }
            for item in payload
        ]

    def list_incidents(self, process_instance_id: str | None = None) -> list[dict[str, Any]]:
        """Open incidents, optionally limited to one process instance."""
        params = {"processInstanceId": process_instance_id} if process_instance_id else {}
        payload = self._request("GET", "/incident", params=params)
        return [
            {
                "id": incident.get("id"),
                "type": incident.get("incidentType"),
                "activity_id": incident.get("activityId"),
                "message": incident.get("incidentMessage"),
                "configuration": incident.get("configuration"),
                "process_instance_id": incident.get("processInstanceId"),
            }
            for incident in payload
        ]

    def delete_process_instance(self, process_instance_id: str, reason: str) -> None:
        """Cancel a running instance. The reason is recorded in the history."""
        self._request(
            "DELETE",
            f"/process-instance/{process_instance_id}",
            params={"skipCustomListeners": "false", "reason": reason},
        )

    # ---- external tasks --------------------------------------------------

    def fetch_and_lock(
        self,
        worker_id: str,
        topics: list[dict[str, Any]],
        max_tasks: int,
        async_response_timeout_ms: int,
    ) -> list[dict[str, Any]]:
        """Long-poll the engine for work on the given topics."""
        return self._request(
            "POST",
            "/external-task/fetchAndLock",
            json={
                "workerId": worker_id,
                "maxTasks": max_tasks,
                "usePriority": False,
                "asyncResponseTimeout": async_response_timeout_ms,
                "topics": topics,
            },
        )

    def complete_external_task(
        self, task_id: str, worker_id: str, variables: dict[str, Any]
    ) -> None:
        """Report an external task as done, with its result variables."""
        self._request(
            "POST",
            f"/external-task/{task_id}/complete",
            json={"workerId": worker_id, "variables": to_engine(variables)},
        )

    def fail_external_task(
        self,
        task_id: str,
        worker_id: str,
        error_message: str,
        error_details: str = "",
        retries: int = 0,
        retry_timeout_ms: int = 0,
    ) -> None:
        """Report an external task as failed. Zero retries creates an incident."""
        self._request(
            "POST",
            f"/external-task/{task_id}/failure",
            json={
                "workerId": worker_id,
                "errorMessage": error_message[:600],
                "errorDetails": error_details,
                "retries": retries,
                "retryTimeout": retry_timeout_ms,
            },
        )

    def bpmn_error_external_task(
        self,
        task_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        variables: dict[str, Any] | None = None,
    ) -> None:
        """Raise a BPMN error from an external task.

        This is not the same as a failure. A failure means the work might
        succeed if it is tried again; a BPMN error means the work will not
        succeed and the process should decide what to do about it, usually
        through an error boundary event.
        """
        self._request(
            "POST",
            f"/external-task/{task_id}/bpmnError",
            json={
                "workerId": worker_id,
                "errorCode": error_code,
                "errorMessage": error_message[:600],
                "variables": to_engine(variables or {}),
            },
        )

    def set_external_task_retries(self, task_id: str, retries: int) -> None:
        """Give a failed external task more attempts, which clears its incident."""
        self._request("PUT", f"/external-task/{task_id}/retries", json={"retries": retries})

    # ---- plumbing --------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise EngineError(f"Could not reach the engine at {self.base_url}: {error}") from error

        if response.status_code >= 400:
            raise EngineError(
                f"{method} {path} failed ({response.status_code}): {_message(response)}"
            )

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _optional(self, method: str, path: str, **kwargs: Any) -> Any | None:
        try:
            return self._request(method, path, **kwargs)
        except EngineError as error:
            if "(404)" in str(error):
                return None
            raise


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:400]
    if isinstance(payload, dict):
        return str(payload.get("message") or payload)[:400]
    return str(payload)[:400]


def _collect_activity_names(node: dict[str, Any], names: list[str]) -> None:
    children = node.get("childActivityInstances") or []
    for child in children:
        _collect_activity_names(child, names)
    if not children and node.get("activityName"):
        names.append(node["activityName"])
