"""The engine client, exercised with httpx.MockTransport - no engine needed."""

import json

import httpx
import pytest

from devflows_core.engine import DEFAULT_ENGINE_URL, EngineClient, EngineError


def client_for(handler) -> EngineClient:
    return EngineClient(transport=httpx.MockTransport(handler))


def test_default_url_matches_the_cib_seven_distribution():
    assert DEFAULT_ENGINE_URL == "http://localhost:8080/engine-rest"


def test_engine_status_reports_version_and_engines():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"version": "2.2.0"})
        return httpx.Response(200, json=[{"name": "default"}])

    status = client_for(handler).engine_status()
    assert status["reachable"] is True
    assert status["version"] == "2.2.0"
    assert status["engines"] == ["default"]
    assert status["error"] is None


def test_engine_status_reports_an_unreachable_engine():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    status = client_for(handler).engine_status()
    assert status["reachable"] is False
    assert status["version"] is None
    assert "connection refused" in status["error"]


def test_deploy_posts_multipart_and_returns_the_deployed_keys(tmp_path):
    bpmn = tmp_path / "release.bpmn"
    bpmn.write_text("<definitions/>", encoding="utf-8")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "id": "dep-1",
                "deployedProcessDefinitions": {
                    "devflows-release:1:abc": {"key": "devflows-release", "version": 1}
                },
            },
        )

    result = client_for(handler).deploy(bpmn)
    assert seen["path"].endswith("/deployment/create")
    assert b"release.bpmn" in seen["body"]
    assert result == {"deployment_id": "dep-1", "process_definition_keys": ["devflows-release"]}


def test_deploy_handles_a_deployment_that_changed_nothing(tmp_path):
    bpmn = tmp_path / "release.bpmn"
    bpmn.write_text("<definitions/>", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "dep-2", "deployedProcessDefinitions": None})

    result = client_for(handler).deploy(bpmn)
    assert result == {"deployment_id": "dep-2", "process_definition_keys": []}


def test_deploy_rejects_a_missing_file(tmp_path):
    with pytest.raises(EngineError, match="does not exist"):
        client_for(lambda r: httpx.Response(200, json={})).deploy(tmp_path / "missing.bpmn")


def test_list_process_definitions_returns_a_small_summary():
    payload = [
        {"key": "devflows-release", "id": "devflows-release:1:a", "version": 1, "name": "Release"}
    ]

    definitions = client_for(lambda r: httpx.Response(200, json=payload)).list_process_definitions()
    assert definitions == [
        {"key": "devflows-release", "id": "devflows-release:1:a", "version": 1, "name": "Release"}
    ]


def test_start_process_sends_encoded_variables_and_returns_the_instance_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "pi-1", "definitionId": "devflows-release:1:a"})

    instance_id = client_for(handler).start_process(
        "devflows-release", {"repo_path": "C:/repo", "dry_run": True}
    )
    assert instance_id == "pi-1"
    assert seen["path"].endswith("/process-definition/key/devflows-release/start")
    assert seen["body"]["variables"]["dry_run"] == {"value": True, "type": "Boolean"}


def test_get_process_instance_returns_none_when_it_has_finished():
    client = client_for(lambda r: httpx.Response(404, json={"message": "not found"}))
    assert client.get_process_instance("pi-1") is None


def test_get_variables_decodes_the_payload():
    payload = {"gates_passed": {"value": True, "type": "Boolean"}}
    client = client_for(lambda r: httpx.Response(200, json=payload))
    assert client.get_variables("pi-1") == {"gates_passed": True}


def test_get_historic_variables_decodes_the_list_shape():
    payload = [
        {"name": "tag_name", "value": "v0.1.0", "type": "String"},
        {"name": "gates_passed", "value": True, "type": "Boolean"},
    ]
    client = client_for(lambda r: httpx.Response(200, json=payload))
    assert client.get_historic_variables("pi-1") == {"tag_name": "v0.1.0", "gates_passed": True}


def test_active_activity_names_come_from_the_activity_instance_tree():
    tree = {
        "id": "pi-1",
        "activityId": "devflows-release",
        "childActivityInstances": [
            {
                "id": "approve:1",
                "activityId": "approve_release",
                "activityName": "Approve release",
                "childActivityInstances": [],
                "childTransitionInstances": [],
            }
        ],
        "childTransitionInstances": [],
    }
    client = client_for(lambda r: httpx.Response(200, json=tree))
    assert client.get_active_activity_names("pi-1") == ["Approve release"]


def test_list_tasks_returns_a_small_summary():
    payload = [
        {
            "id": "task-1",
            "name": "Approve release",
            "assignee": None,
            "processInstanceId": "pi-1",
            "created": "2026-08-22T10:00:00.000+0000",
        }
    ]
    tasks = client_for(lambda r: httpx.Response(200, json=payload)).list_tasks("pi-1")
    assert tasks == [
        {
            "id": "task-1",
            "name": "Approve release",
            "assignee": None,
            "process_instance_id": "pi-1",
            "created": "2026-08-22T10:00:00.000+0000",
        }
    ]


def test_complete_task_sends_encoded_variables():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(204)

    client_for(handler).complete_task("task-1", {"approved": True, "approval_comment": "ship it"})
    assert seen["path"].endswith("/task/task-1/complete")
    assert seen["body"]["variables"]["approved"] == {"value": True, "type": "Boolean"}


def test_fetch_and_lock_posts_the_topic_list():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"id": "et-1", "topicName": "devflows.gates"}])

    topics = [{"topicName": "devflows.gates", "lockDuration": 60000}]
    tasks = client_for(handler).fetch_and_lock("worker-1", topics, 5, 10000)
    assert tasks[0]["id"] == "et-1"
    assert seen["body"]["workerId"] == "worker-1"
    assert seen["body"]["maxTasks"] == 5
    assert seen["body"]["asyncResponseTimeout"] == 10000
    assert seen["body"]["topics"] == topics


def test_complete_external_task_sends_worker_id_and_variables():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(204)

    client_for(handler).complete_external_task("et-1", "worker-1", {"gates_passed": True})
    assert seen["path"].endswith("/external-task/et-1/complete")
    assert seen["body"]["workerId"] == "worker-1"
    assert seen["body"]["variables"]["gates_passed"]["value"] is True


def test_fail_external_task_sends_the_message_and_details():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(204)

    client_for(handler).fail_external_task("et-1", "worker-1", "gate failed", "pytest output")
    assert seen["path"].endswith("/external-task/et-1/failure")
    assert seen["body"]["errorMessage"] == "gate failed"
    assert seen["body"]["errorDetails"] == "pytest output"
    assert seen["body"]["retries"] == 0


def test_a_server_error_is_reported_with_the_engine_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "ENGINE-09999 something broke"})

    with pytest.raises(EngineError, match="ENGINE-09999"):
        client_for(handler).list_process_definitions()


def test_the_client_works_as_a_context_manager():
    with client_for(lambda r: httpx.Response(200, json=[])) as client:
        assert client.list_process_definitions() == []


def test_the_environment_variable_sets_the_base_url(monkeypatch):
    monkeypatch.setenv("DEVFLOWS_ENGINE_URL", "http://example.invalid:9000/engine-rest/")
    client = EngineClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    assert client.base_url == "http://example.invalid:9000/engine-rest"
