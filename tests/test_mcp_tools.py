"""The seven MCP tools, against a fake engine client."""

import json

import pytest

from devflows_core.engine import EngineError
from devflows_mcp import tools

CONFIG = """
gates:
  - name: tests
    run: uv run pytest -q
publish:
  run: gh release create v{version}
"""


class FakeClient:
    def __init__(self, **responses):
        self.responses = responses
        self.calls = []

    def _answer(self, name, default=None):
        self.calls.append(name)
        value = self.responses.get(name, default)
        if isinstance(value, Exception):
            raise value
        return value

    def engine_status(self):
        return self._answer(
            "engine_status",
            {
                "reachable": True,
                "version": "2.2.0",
                "engines": ["default"],
                "url": "http://localhost:8080/engine-rest",
                "error": None,
            },
        )

    def deploy(self, path):
        self.deployed_path = path
        return self._answer(
            "deploy", {"deployment_id": "dep-1", "process_definition_keys": ["devflows-release"]}
        )

    def list_process_definitions(self):
        return self._answer("list_process_definitions", [])

    def start_process(self, key, variables):
        self.started = (key, variables)
        return self._answer("start_process", "pi-1")

    def get_process_instance(self, pid):
        return self._answer("get_process_instance", None)

    def get_historic_process_instance(self, pid):
        return self._answer("get_historic_process_instance", None)

    def get_variables(self, pid):
        return self._answer("get_variables", {})

    def get_historic_variables(self, pid):
        return self._answer("get_historic_variables", {})

    def get_active_activity_names(self, pid):
        return self._answer("get_active_activity_names", [])

    def list_tasks(self, pid=None):
        return self._answer("list_tasks", [])

    def complete_task(self, task_id, variables):
        self.completed = (task_id, variables)
        return self._answer("complete_task", None)


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "devflows.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


# ---- engine_status -------------------------------------------------------


def test_engine_status_passes_the_engine_answer_through():
    result = tools.engine_status(FakeClient())
    assert result["ok"] is True
    assert result["version"] == "2.2.0"


def test_engine_status_is_not_ok_when_the_engine_is_down():
    client = FakeClient(
        engine_status={
            "reachable": False,
            "version": None,
            "engines": [],
            "url": "http://localhost:8080/engine-rest",
            "error": "connection refused",
        }
    )
    result = tools.engine_status(client)
    assert result["ok"] is False
    assert "connection refused" in result["error"]


# ---- deploy_process ------------------------------------------------------


def test_deploy_process_uses_the_bundled_bpmn_by_default():
    client = FakeClient()
    result = tools.deploy_process(client)
    assert result["ok"] is True
    assert result["process_definition_keys"] == ["devflows-release"]
    assert client.deployed_path.name == "release.bpmn"


def test_deploy_process_accepts_an_explicit_path(tmp_path):
    custom = tmp_path / "other.bpmn"
    custom.write_text("<definitions/>", encoding="utf-8")
    client = FakeClient()
    tools.deploy_process(client, str(custom))
    assert client.deployed_path == custom


def test_deploy_process_reports_an_engine_error():
    client = FakeClient(deploy=EngineError("deployment failed (400): bad BPMN"))
    result = tools.deploy_process(client)
    assert result["ok"] is False
    assert "bad BPMN" in result["error"]


# ---- list_processes ------------------------------------------------------


def test_list_processes_returns_the_definitions():
    definitions = [{"key": "devflows-release", "id": "x", "version": 1, "name": "Release ritual"}]
    result = tools.list_processes(FakeClient(list_process_definitions=definitions))
    assert result["ok"] is True
    assert result["process_definitions"] == definitions


# ---- start_release -------------------------------------------------------


def test_start_release_sends_the_three_start_variables(repo):
    client = FakeClient()
    result = tools.start_release(client, str(repo), "0.1.0", dry_run=True)
    key, variables = client.started
    assert key == "devflows-release"
    assert variables == {"repo_path": str(repo), "version": "0.1.0", "dry_run": True}
    assert result["ok"] is True
    assert result["process_instance_id"] == "pi-1"


def test_start_release_defaults_to_a_dry_run(repo):
    client = FakeClient()
    tools.start_release(client, str(repo), "0.1.0")
    assert client.started[1]["dry_run"] is True


def test_start_release_gives_back_a_link_to_the_instance(repo):
    result = tools.start_release(FakeClient(), str(repo), "0.1.0")
    assert result["instance_url"].endswith("pi-1")
    # The older /camunda/app/ webapps are deprecated in CIB seven 2.2.
    assert "/camunda/app/" not in result["instance_url"]


def test_start_release_refuses_a_repository_without_a_config(tmp_path):
    result = tools.start_release(FakeClient(), str(tmp_path), "0.1.0")
    assert result["ok"] is False
    assert "devflows.yaml" in result["error"]


def test_start_release_refuses_an_empty_version(repo):
    result = tools.start_release(FakeClient(), str(repo), "  ")
    assert result["ok"] is False
    assert "version" in result["error"]


# ---- get_run -------------------------------------------------------------


def test_get_run_reports_a_running_instance_with_its_current_activity():
    client = FakeClient(
        get_process_instance={"id": "pi-1", "ended": False, "suspended": False},
        get_variables={"gates_passed": True},
        get_active_activity_names=["Approve release"],
        list_tasks=[
            {
                "id": "task-1",
                "name": "Approve release",
                "assignee": None,
                "process_instance_id": "pi-1",
                "created": "2026-08-22T10:00:00.000+0000",
            }
        ],
    )
    result = tools.get_run(client, "pi-1")
    assert result["ok"] is True
    assert result["state"] == "running"
    assert result["active_activities"] == ["Approve release"]
    assert result["variables"]["gates_passed"] is True
    assert result["open_tasks"][0]["id"] == "task-1"


def test_get_run_falls_back_to_history_for_a_finished_instance():
    client = FakeClient(
        get_process_instance=None,
        get_historic_process_instance={"id": "pi-1", "state": "COMPLETED"},
        get_historic_variables={"release_url": "https://example.invalid/r/v0.1.0"},
    )
    result = tools.get_run(client, "pi-1")
    assert result["ok"] is True
    assert result["state"] == "COMPLETED"
    assert result["variables"]["release_url"] == "https://example.invalid/r/v0.1.0"
    assert result["open_tasks"] == []


def test_get_run_reports_an_unknown_instance():
    client = FakeClient(get_process_instance=None, get_historic_process_instance=None)
    result = tools.get_run(client, "pi-nope")
    assert result["ok"] is False
    assert "pi-nope" in result["error"]


def test_get_run_decodes_the_gate_report_for_the_caller():
    report = json.dumps([{"name": "tests", "passed": False, "exit_code": 1, "output": "boom"}])
    client = FakeClient(
        get_process_instance=None,
        get_historic_process_instance={"id": "pi-1", "state": "COMPLETED"},
        get_historic_variables={"gates_report": report, "gates_passed": False},
    )
    result = tools.get_run(client, "pi-1")
    assert result["gates"][0]["name"] == "tests"
    assert result["gates"][0]["passed"] is False


def test_get_run_tolerates_a_gate_report_that_is_not_json():
    client = FakeClient(
        get_process_instance=None,
        get_historic_process_instance={"id": "pi-1", "state": "COMPLETED"},
        get_historic_variables={"gates_report": "not json at all"},
    )
    assert tools.get_run(client, "pi-1")["gates"] == []


# ---- list_gates ----------------------------------------------------------


def test_list_gates_reads_the_repository_config(repo):
    result = tools.list_gates(str(repo))
    assert result["ok"] is True
    assert result["gates"] == [{"name": "tests", "run": "uv run pytest -q"}]
    assert result["tag_format"] == "v{version}"


def test_list_gates_reports_a_repository_without_a_config(tmp_path):
    result = tools.list_gates(str(tmp_path))
    assert result["ok"] is False
    assert "devflows.yaml" in result["error"]


# ---- approve_gate --------------------------------------------------------


def test_approve_gate_completes_the_task_with_approved_true():
    client = FakeClient()
    result = tools.approve_gate(client, "task-1", True, "ship it")
    assert client.completed == ("task-1", {"approved": True, "approval_comment": "ship it"})
    assert result["ok"] is True
    assert result["approved"] is True


def test_approve_gate_can_also_reject():
    client = FakeClient()
    result = tools.approve_gate(client, "task-1", False, "not yet")
    assert client.completed[1]["approved"] is False
    assert result["approved"] is False


def test_approve_gate_reports_an_unknown_task():
    client = FakeClient(complete_task=EngineError("POST /task/x/complete failed (404): no task"))
    result = tools.approve_gate(client, "x", True)
    assert result["ok"] is False
    assert "404" in result["error"]
