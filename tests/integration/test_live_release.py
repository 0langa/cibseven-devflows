"""Deploy the real process, run one dry release end to end, check the history.

No separate worker process is started here. The test does what the worker does -
fetch, handle, complete - by calling the same functions, so a failure points at
the code rather than at process management.

A real `devflows-worker` may also be running against the same engine while these
tests run. That is fine: whichever worker locks a task first does it. The helper
below therefore waits for the *outcome* in the engine, not for its own poll to
be the one that produced it.

Every test in this module is marked `integration`. This repository's own gate
command excludes that marker, because these tests run a release, and a release
runs the gates: without the marker the gate step would start a release from
inside a release.
"""

import subprocess
import time

import pytest

from devflows_core.engine import PROCESS_KEY
from devflows_core.paths import default_bpmn_path
from devflows_worker.main import poll_once

pytestmark = pytest.mark.integration

REPO_ROOT = default_bpmn_path().parent.parent
WORKER_ID = "integration-test-worker"
DEADLINE_SECONDS = 300


@pytest.fixture(scope="module")
def deployed(live_engine):
    result = live_engine.deploy(default_bpmn_path())
    assert result["deployment_id"]
    return live_engine


def advance(client, until, deadline_seconds=DEADLINE_SECONDS):
    """Act as a worker until the engine reaches the state we are waiting for."""
    stop_at = time.monotonic() + deadline_seconds
    while time.monotonic() < stop_at:
        if until():
            return
        poll_once(client, WORKER_ID, async_timeout_ms=1000)
    raise AssertionError("The process did not reach the expected state in time")


def waiting_for_a_human(client, instance_id):
    """True once a user task is open, or the instance has already ended."""

    def check():
        if client.list_tasks(instance_id):
            return True
        return client.get_process_instance(instance_id) is None

    return check


def finished(client, instance_id):
    """True once the instance is no longer running."""
    return lambda: client.get_process_instance(instance_id) is None


def test_git_is_available():
    # The gates in this repository shell out; if git is missing the rest is noise.
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


def test_a_dry_run_reaches_the_approval_task_and_then_completes(deployed):
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(REPO_ROOT), "version": "0.0.0-integration", "dry_run": True},
    )

    # The gates run, then the process stops and waits for a person.
    advance(client, waiting_for_a_human(client, instance_id))

    variables = client.get_variables(instance_id)
    assert variables["gates_passed"] is True, variables.get("gates_report")

    tasks = client.list_tasks(instance_id)
    assert len(tasks) == 1
    assert tasks[0]["name"] == "Approve release"

    # Approve it the way the MCP tool does.
    client.complete_task(tasks[0]["id"], {"approved": True, "approval_comment": "integration test"})

    # The tag and publish steps run - but this is a dry run, so nothing happens for real.
    advance(client, finished(client, instance_id))

    historic = client.get_historic_process_instance(instance_id)
    assert historic["state"] == "COMPLETED"

    result = client.get_historic_variables(instance_id)
    assert result["tag_name"] == "v0.0.0-integration"
    assert result["published"] is False
    assert "dry run" in result["release_url"].lower()

    # A dry run must not have touched the repository.
    tags = subprocess.run(
        ["git", "tag", "--list", "v0.0.0-integration"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert tags.stdout.strip() == ""


def test_a_rejected_release_ends_without_tagging(deployed):
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(REPO_ROOT), "version": "0.0.0-rejected", "dry_run": True},
    )
    advance(client, waiting_for_a_human(client, instance_id))

    tasks = client.list_tasks(instance_id)
    assert len(tasks) == 1
    client.complete_task(tasks[0]["id"], {"approved": False, "approval_comment": "not yet"})
    advance(client, finished(client, instance_id))

    result = client.get_historic_variables(instance_id)
    assert result["approved"] is False
    assert "tag_name" not in result


def test_failing_gates_end_the_process_without_asking_a_human(deployed, tmp_path):
    """A repository whose gates fail never reaches the approval task."""
    (tmp_path / "devflows.yaml").write_text(
        "gates:\n  - name: impossible\n    run: exit 7\npublish:\n  run: echo nothing\n",
        encoding="utf-8",
    )
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(tmp_path), "version": "0.0.0-failing", "dry_run": True},
    )
    advance(client, finished(client, instance_id))

    assert client.list_tasks(instance_id) == []

    result = client.get_historic_variables(instance_id)
    assert result["gates_passed"] is False
    assert "impossible" in result["gates_report"]
