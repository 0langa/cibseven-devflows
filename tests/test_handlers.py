"""The three external task handlers, with the shell runner replaced by a fake."""

import json

import pytest

from devflows_core.steps import StepResult
from devflows_worker.handlers import (
    GATES_TOPIC,
    HANDLERS,
    PUBLISH_TOPIC,
    TAG_TOPIC,
    HandlerError,
    handle_gates,
    handle_publish,
    handle_tag,
)

CONFIG = """
gates:
  - name: tests
    run: pytest -q
  - name: lint
    run: ruff check .

tag:
  format: "v{version}"

publish:
  run: gh release create v{version} --generate-notes
"""


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "devflows.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def fake_runner(results):
    """Return a runner that replays canned results and records the commands."""
    calls = []

    def runner(command, cwd, timeout=900):
        calls.append(command)
        outcome = results.pop(0) if results else 0
        if isinstance(outcome, StepResult):
            return outcome
        return StepResult(command=command, exit_code=outcome, output="ok", duration_seconds=0.1)

    runner.calls = calls
    return runner


def test_every_topic_has_a_handler():
    assert set(HANDLERS) == {GATES_TOPIC, TAG_TOPIC, PUBLISH_TOPIC}


# ---- gates ---------------------------------------------------------------


def test_gates_pass_when_every_command_exits_zero(repo):
    runner = fake_runner([0, 0])
    result = handle_gates({"repo_path": str(repo), "dry_run": False}, runner=runner)
    assert result["gates_passed"] is True
    report = json.loads(result["gates_report"])
    assert [entry["name"] for entry in report] == ["tests", "lint"]
    assert all(entry["passed"] for entry in report)
    assert runner.calls == ["pytest -q", "ruff check ."]


def test_gates_fail_when_one_command_fails(repo):
    runner = fake_runner([1, 0])
    result = handle_gates({"repo_path": str(repo), "dry_run": False}, runner=runner)
    assert result["gates_passed"] is False
    report = json.loads(result["gates_report"])
    assert report[0]["passed"] is False
    assert report[0]["exit_code"] == 1


def test_gates_stop_at_the_first_failure(repo):
    runner = fake_runner([1, 0])
    handle_gates({"repo_path": str(repo), "dry_run": False}, runner=runner)
    assert runner.calls == ["pytest -q"]


def test_gates_run_for_real_even_in_a_dry_run(repo):
    runner = fake_runner([0, 0])
    result = handle_gates({"repo_path": str(repo), "dry_run": True}, runner=runner)
    assert runner.calls == ["pytest -q", "ruff check ."]
    assert result["gates_passed"] is True


def test_gates_report_a_missing_config_as_a_handler_error(tmp_path):
    with pytest.raises(HandlerError, match="No devflows.yaml"):
        handle_gates({"repo_path": str(tmp_path), "dry_run": False}, runner=fake_runner([]))


def test_gates_require_repo_path():
    with pytest.raises(HandlerError, match="repo_path"):
        handle_gates({"dry_run": False}, runner=fake_runner([]))


# ---- tag -----------------------------------------------------------------


def test_tag_builds_the_name_from_the_configured_format(repo):
    runner = fake_runner([0])
    result = handle_tag(
        {"repo_path": str(repo), "version": "0.1.0", "dry_run": False}, runner=runner
    )
    assert result["tag_name"] == "v0.1.0"
    assert result["tag_created"] is True
    assert runner.calls == ['git tag -a v0.1.0 -m "Release v0.1.0"']


def test_tag_creates_nothing_in_a_dry_run(repo):
    runner = fake_runner([])
    result = handle_tag(
        {"repo_path": str(repo), "version": "0.1.0", "dry_run": True}, runner=runner
    )
    assert result["tag_name"] == "v0.1.0"
    assert result["tag_created"] is False
    assert runner.calls == []


def test_tag_requires_a_version(repo):
    with pytest.raises(HandlerError, match="version"):
        handle_tag({"repo_path": str(repo), "dry_run": False}, runner=fake_runner([]))


def test_tag_reports_a_failing_git_command(repo):
    failed = StepResult(
        command="git tag", exit_code=128, output="fatal: tag already exists", duration_seconds=0.1
    )
    with pytest.raises(HandlerError, match="already exists"):
        handle_tag(
            {"repo_path": str(repo), "version": "0.1.0", "dry_run": False},
            runner=fake_runner([failed]),
        )


# ---- publish -------------------------------------------------------------


def test_publish_checks_gh_pushes_the_tag_and_creates_the_release(repo):
    created = StepResult(
        command="gh release create",
        exit_code=0,
        output="https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0",
        duration_seconds=0.2,
    )
    runner = fake_runner([0, 0, created])
    result = handle_publish(
        {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": False},
        runner=runner,
    )
    assert runner.calls == [
        "gh auth status",
        "git push origin v0.1.0",
        "gh release create v0.1.0 --generate-notes",
    ]
    assert result["published"] is True
    assert result["release_url"] == (
        "https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0"
    )


def test_publish_does_nothing_in_a_dry_run(repo):
    runner = fake_runner([])
    result = handle_publish(
        {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": True},
        runner=runner,
    )
    assert runner.calls == []
    assert result["published"] is False
    assert "dry run" in result["release_url"].lower()
    assert "gh release create v0.1.0 --generate-notes" in result["publish_command"]


def test_publish_fails_clearly_when_gh_is_not_authenticated(repo):
    not_logged_in = StepResult(
        command="gh auth status",
        exit_code=1,
        output="You are not logged into any GitHub hosts.",
        duration_seconds=0.1,
    )
    with pytest.raises(HandlerError, match="gh"):
        handle_publish(
            {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": False},
            runner=fake_runner([not_logged_in]),
        )


def test_publish_falls_back_to_the_tag_name_from_the_config(repo):
    created = StepResult(command="gh", exit_code=0, output="no url here", duration_seconds=0.1)
    runner = fake_runner([0, 0, created])
    result = handle_publish(
        {"repo_path": str(repo), "version": "0.1.0", "dry_run": False}, runner=runner
    )
    assert "git push origin v0.1.0" in runner.calls
    assert result["release_url"] == ""
