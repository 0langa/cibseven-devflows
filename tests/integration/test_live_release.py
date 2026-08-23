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


# ---- v0.2.0 paths --------------------------------------------------------


def make_repo(tmp_path, publish="echo published https://example.invalid/r", tag=None):
    """A throwaway git repository the process can safely tag and untag."""
    config = "gates:\n  - name: trivial\n    run: echo fine\n"
    config += 'tag:\n  format: "v{version}"\n'
    config += f"publish:\n  run: {publish}\n"
    (tmp_path / "devflows.yaml").write_text(config, encoding="utf-8")

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "devflows integration test")
    git("commit", "-q", "--allow-empty", "-m", "first commit")
    if tag:
        git("tag", tag)
    return tmp_path


def tags_in(repo):
    listed = subprocess.run(
        ["git", "tag", "--list"], cwd=repo, capture_output=True, text=True
    )
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def test_a_patch_release_is_approved_by_policy_and_never_asks_a_human(deployed, tmp_path):
    """The DMN table decides. A patch with green gates does not stop."""
    repo = make_repo(tmp_path, tag="v1.2.3")
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(repo), "version": "1.2.4", "dry_run": True},
    )
    advance(client, finished(client, instance_id))

    result = client.get_historic_variables(instance_id)
    assert result["release_kind"] == "patch"
    assert result["previous_version"] == "v1.2.3"
    # No human was asked, so nobody set `approved`.
    assert "approved" not in result
    assert result["tag_name"] == "v1.2.4"
    assert client.get_historic_process_instance(instance_id)["state"] == "COMPLETED"


def test_a_minor_release_stops_for_a_human(deployed, tmp_path):
    repo = make_repo(tmp_path, tag="v1.2.3")
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(repo), "version": "1.3.0", "dry_run": True},
    )
    advance(client, waiting_for_a_human(client, instance_id))

    tasks = client.list_tasks(instance_id)
    assert len(tasks) == 1, "a minor release must not be auto-approved"

    variables = client.get_variables(instance_id)
    assert variables["release_kind"] == "minor"
    # The notes are drafted before the human sees them.
    assert variables["release_notes"].strip()
    assert variables["notes_source"] in {"claude", "git-log"}

    client.complete_task(tasks[0]["id"], {"approved": False, "approval_comment": "no"})
    advance(client, finished(client, instance_id))


def test_the_approval_timer_ends_a_forgotten_release(deployed, tmp_path):
    """Nobody answers, so the process rejects itself instead of hanging."""
    repo = make_repo(tmp_path, tag="v1.2.3")
    client = deployed
    instance_id = client.start_process(
        PROCESS_KEY,
        {
            "repo_path": str(repo),
            "version": "1.3.0",
            "dry_run": True,
            "approval_timeout": "PT5S",
        },
    )
    advance(client, waiting_for_a_human(client, instance_id))
    assert client.list_tasks(instance_id), "the run should be waiting for a human"

    # Do not answer. The boundary timer has to end it.
    advance(client, finished(client, instance_id), deadline_seconds=120)

    assert client.list_tasks(instance_id) == []
    assert client.get_historic_process_instance(instance_id)["state"] == "COMPLETED"


def test_a_failed_publish_compensates_and_removes_the_tag(deployed, tmp_path):
    """The whole point of compensation: no half-finished release is left behind."""
    repo = make_repo(tmp_path, tag="v1.2.3")
    client = deployed
    # dry_run is false, so the tag is real. There is no remote, so pushing it
    # fails, which is a BusinessError and therefore a BPMN error.
    instance_id = client.start_process(
        PROCESS_KEY,
        {"repo_path": str(repo), "version": "1.2.4", "dry_run": False},
    )
    advance(client, finished(client, instance_id))

    result = client.get_historic_variables(instance_id)
    assert result["tag_created"] is True, "the tag step has to run before compensation matters"
    assert result["tag_deleted"] is True, "compensation must delete the tag it created"

    # And it is really gone from the repository, not just claimed to be.
    assert "v1.2.4" not in tags_in(repo)
    assert "v1.2.3" in tags_in(repo), "compensation must not touch older tags"

    # A caught BPMN error is not an incident: nothing is broken.
    assert client.list_incidents(instance_id) == []
