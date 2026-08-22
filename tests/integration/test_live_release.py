"""Deploy the real process, run one dry release end to end, check the history.

The worker is not started as a separate process here. The test does what the
worker does - fetch, handle, complete - by calling the same functions, so a
failure points at the code rather than at process management.

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

pytestmark = pytest.mark.integration

REPO_ROOT = default_bpmn_path().parent.parent
WORKER_ID = "integration-test-worker"


@pytest.fixture(scope="module")
def deployed(live_engine):
    result = live_engine.deploy(default_bpmn_path())
    assert result["deployment_id"]
    return live_engine


def drain(client, deadline_seconds=300):
    """Let the worker logic handle whatever work the engine offers."""
    from devflows_worker.main import poll_once

    stop_at = time.monotonic() + deadline_seconds
    while time.monotonic() < stop_at:
        if poll_once(client, WORKER_ID, async_timeout_ms=1000) == 0:
            return
    raise AssertionError("The engine kept offering work for too long")


def test_git_is_available():
    # The gates in this repository shell out; if git is missing the rest is noise.
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


def test_a_dry_run_reaches_the_approval_task_and_then_completes(deployed):
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(REPO_ROOT), "version": "0.0.0-integration", "dry_run": True},
    )

    # The worker runs the gates.
    drain(client)

    variables = client.get_variables(instance_id)
    assert variables["gates_passed"] is True, variables.get("gates_report")

    # The process is now waiting for a human.
    tasks = client.list_tasks(instance_id)
    assert len(tasks) == 1
    assert tasks[0]["name"] == "Approve release"

    # Approve it the way the MCP tool does.
    client.complete_task(tasks[0]["id"], {"approved": True, "approval_comment": "integration test"})

    # The worker tags and publishes - but this is a dry run, so nothing happens for real.
    drain(client)

    assert client.get_process_instance(instance_id) is None

    historic = client.get_historic_process_instance(instance_id)
    assert historic["state"] == "COMPLETED"

    finished = client.get_historic_variables(instance_id)
    assert finished["tag_name"] == "v0.0.0-integration"
    assert finished["published"] is False
    assert "dry run" in finished["release_url"].lower()

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
    drain(client)

    tasks = client.list_tasks(instance_id)
    assert len(tasks) == 1
    client.complete_task(tasks[0]["id"], {"approved": False, "approval_comment": "not yet"})
    drain(client)

    finished = client.get_historic_variables(instance_id)
    assert finished["approved"] is False
    assert "tag_name" not in finished


def test_failing_gates_end_the_process_without_asking_a_human(deployed, tmp_path):
    """A repository whose gates fail never reaches the approval task."""
    (tmp_path / "devflows.yaml").write_text(
        'gates:\n  - name: impossible\n    run: exit 7\npublish:\n  run: echo nothing\n',
        encoding="utf-8",
    )
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(tmp_path), "version": "0.0.0-failing", "dry_run": True},
    )
    drain(client)

    assert client.list_tasks(instance_id) == []
    assert client.get_process_instance(instance_id) is None

    finished = client.get_historic_variables(instance_id)
    assert finished["gates_passed"] is False
    assert "impossible" in finished["gates_report"]
