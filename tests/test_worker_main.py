"""The fetch-and-lock loop, with a fake engine client."""

from devflows_worker.handlers import (
    GATES_TOPIC,
    NOTES_TOPIC,
    PUBLISH_TOPIC,
    TAG_TOPIC,
    UNTAG_TOPIC,
    BusinessError,
    HandlerError,
)
from devflows_worker.main import RETRY_BACKOFF_MS, build_topics, handle_one, poll_once


class FakeClient:
    """Records what the worker asked the engine to do."""

    def __init__(self, tasks=None):
        self.tasks = tasks or []
        self.completed = []
        self.failed = []
        self.bpmn_errors = []
        self.last_failure = {}

    def fetch_and_lock(self, worker_id, topics, max_tasks, async_response_timeout_ms):
        tasks, self.tasks = self.tasks, []
        return tasks

    def complete_external_task(self, task_id, worker_id, variables):
        self.completed.append((task_id, variables))

    def fail_external_task(self, task_id, worker_id, error_message, error_details="", **kwargs):
        self.failed.append((task_id, error_message, error_details))
        self.last_failure = kwargs

    def bpmn_error_external_task(self, task_id, worker_id, error_code, error_message, **kwargs):
        self.bpmn_errors.append((task_id, error_code, error_message))


def test_the_worker_subscribes_to_every_topic():
    topics = build_topics(60000)
    assert [topic["topicName"] for topic in topics] == [
        GATES_TOPIC,
        NOTES_TOPIC,
        TAG_TOPIC,
        PUBLISH_TOPIC,
        UNTAG_TOPIC,
    ]
    assert all(topic["lockDuration"] == 60000 for topic in topics)


def test_topics_ask_only_for_the_variables_the_handlers_need():
    for topic in build_topics():
        assert set(topic["variables"]) == {
            "repo_path",
            "version",
            "dry_run",
            "tag_name",
            "release_notes",
            "notes_override",
            "approval_timeout",
        }


def test_a_successful_handler_completes_the_task():
    client = FakeClient()
    task = {
        "id": "et-1",
        "topicName": GATES_TOPIC,
        "variables": {"repo_path": {"value": "C:/repo", "type": "String"}},
    }
    handlers = {GATES_TOPIC: lambda variables: {"gates_passed": True}}

    outcome = handle_one(client, "worker-1", task, handlers=handlers)

    assert outcome == "completed"
    assert client.completed == [("et-1", {"gates_passed": True})]
    assert client.failed == []


def test_variables_reach_the_handler_already_decoded():
    seen = {}

    def handler(variables):
        seen.update(variables)
        return {}

    task = {
        "id": "et-1",
        "topicName": GATES_TOPIC,
        "variables": {
            "repo_path": {"value": "C:/repo", "type": "String"},
            "dry_run": {"value": True, "type": "Boolean"},
        },
    }
    handle_one(FakeClient(), "worker-1", task, handlers={GATES_TOPIC: handler})

    assert seen == {"repo_path": "C:/repo", "dry_run": True}


def test_a_handler_error_fails_the_task_with_its_message():
    client = FakeClient()

    def handler(variables):
        raise HandlerError("gate failed", "pytest said no")

    task = {"id": "et-1", "topicName": GATES_TOPIC, "variables": {}}
    outcome = handle_one(client, "worker-1", task, handlers={GATES_TOPIC: handler})

    assert outcome == "failed"
    assert client.completed == []
    assert client.failed == [("et-1", "gate failed", "pytest said no")]


def test_the_first_failure_leaves_retries_rather_than_raising_an_incident():
    client = FakeClient()

    def handler(variables):
        raise HandlerError("flaky", "")

    # retries is None the first time the engine hands a task out.
    task = {"id": "et-1", "topicName": GATES_TOPIC, "variables": {}, "retries": None}
    handle_one(client, "worker-1", task, handlers={GATES_TOPIC: handler})

    assert client.last_failure["retries"] == len(RETRY_BACKOFF_MS)
    assert client.last_failure["retry_timeout_ms"] == RETRY_BACKOFF_MS[0]


def test_each_further_failure_waits_longer():
    client = FakeClient()

    def handler(variables):
        raise HandlerError("flaky", "")

    task = {"id": "et-1", "topicName": GATES_TOPIC, "variables": {}, "retries": 3}
    handle_one(client, "worker-1", task, handlers={GATES_TOPIC: handler})

    assert client.last_failure["retries"] == 2
    assert client.last_failure["retry_timeout_ms"] == RETRY_BACKOFF_MS[1]


def test_the_last_failure_raises_an_incident():
    client = FakeClient()

    def handler(variables):
        raise HandlerError("still broken", "")

    task = {"id": "et-1", "topicName": GATES_TOPIC, "variables": {}, "retries": 1}
    handle_one(client, "worker-1", task, handlers={GATES_TOPIC: handler})

    assert client.last_failure["retries"] == 0


def test_a_business_error_becomes_a_bpmn_error_not_a_failure():
    client = FakeClient()

    def handler(variables):
        raise BusinessError("PUBLISH_FAILED", "gh said no")

    task = {"id": "et-1", "topicName": PUBLISH_TOPIC, "variables": {}}
    outcome = handle_one(client, "worker-1", task, handlers={PUBLISH_TOPIC: handler})

    assert outcome == "bpmn-error"
    assert client.failed == []
    assert client.bpmn_errors == [("et-1", "PUBLISH_FAILED", "gh said no")]


def test_an_unexpected_exception_also_fails_the_task():
    client = FakeClient()

    def handler(variables):
        raise ValueError("something odd")

    task = {"id": "et-1", "topicName": GATES_TOPIC, "variables": {}}
    outcome = handle_one(client, "worker-1", task, handlers={GATES_TOPIC: handler})

    assert outcome == "failed"
    assert "something odd" in client.failed[0][1]
    # An unexpected exception is still worth retrying; the machine may recover.
    assert client.last_failure["retries"] == len(RETRY_BACKOFF_MS)


def test_an_unknown_topic_fails_the_task():
    client = FakeClient()
    task = {"id": "et-1", "topicName": "devflows.nope", "variables": {}}

    outcome = handle_one(client, "worker-1", task, handlers={})

    assert outcome == "failed"
    assert "devflows.nope" in client.failed[0][1]


def test_poll_once_reports_how_many_tasks_it_handled():
    task = {"id": "et-1", "topicName": TAG_TOPIC, "variables": {}}
    client = FakeClient([task])
    handled = poll_once(client, "worker-1", handlers={TAG_TOPIC: lambda variables: {}})
    assert handled == 1


def test_poll_once_returns_zero_when_there_is_no_work():
    assert poll_once(FakeClient(), "worker-1", handlers={}) == 0
