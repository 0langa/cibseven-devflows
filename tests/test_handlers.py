"""The external task handlers, with the shell runner replaced by a fake."""

import json
from pathlib import Path

import pytest

from devflows_core.steps import StepResult
from devflows_worker.handlers import (
    DEFAULT_APPROVAL_TIMEOUT,
    GATES_TOPIC,
    HANDLERS,
    NOTES_TOPIC,
    PUBLISH_FAILED,
    PUBLISH_TOPIC,
    TAG_TOPIC,
    UNTAG_TOPIC,
    BusinessError,
    HandlerError,
    handle_gates,
    handle_notes,
    handle_publish,
    handle_tag,
    handle_untag,
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
    """Return a runner that replays canned results and records what it was asked."""
    calls = []
    stdins = []

    def runner(command, cwd, timeout=900, stdin=None):
        calls.append(command)
        stdins.append(stdin)
        outcome = results.pop(0) if results else 0
        if isinstance(outcome, StepResult):
            return outcome
        return StepResult(command=command, exit_code=outcome, output="ok", duration_seconds=0.1)

    runner.calls = calls
    runner.stdins = stdins
    return runner


def test_every_topic_has_a_handler():
    assert set(HANDLERS) == {
        GATES_TOPIC,
        NOTES_TOPIC,
        TAG_TOPIC,
        PUBLISH_TOPIC,
        UNTAG_TOPIC,
    }


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


def test_a_failed_push_is_a_business_error_so_the_process_can_compensate(repo):
    refused = StepResult(
        command="git push", exit_code=1, output="remote rejected", duration_seconds=0.1
    )
    with pytest.raises(BusinessError) as raised:
        handle_publish(
            {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": False},
            runner=fake_runner([0, refused]),
        )
    assert raised.value.code == PUBLISH_FAILED


def test_a_failed_release_command_is_a_business_error(repo):
    refused = StepResult(command="gh", exit_code=1, output="gh said no", duration_seconds=0.1)
    with pytest.raises(BusinessError) as raised:
        handle_publish(
            {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": False},
            runner=fake_runner([0, 0, refused]),
        )
    assert raised.value.code == PUBLISH_FAILED
    assert "gh said no" in raised.value.message


def test_a_missing_gh_login_stays_a_retryable_failure(repo):
    # Logging in and trying again works, so this must not compensate the tag away.
    not_logged_in = StepResult(
        command="gh auth status", exit_code=1, output="not logged in", duration_seconds=0.1
    )
    with pytest.raises(HandlerError):
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


# ---- notes ---------------------------------------------------------------


def step(output, exit_code=0):
    """One canned result for fake_runner to replay."""
    return StepResult(command="canned", exit_code=exit_code, output=output, duration_seconds=0.1)


TAG_LIST = "git tag --list --sort=-v:refname"


def test_the_notes_topic_is_registered():
    assert HANDLERS[NOTES_TOPIC] is handle_notes


def test_notes_come_from_claude_when_the_call_succeeds(repo):
    runner = fake_runner([step("v0.1.0\nv0.0.9"), step("abc123 feat: a feature"), step("## Added")])
    result = handle_notes({"repo_path": str(repo), "version": "0.2.0"}, runner=runner)
    assert result["notes_source"] == "claude"
    assert result["release_notes"] == "## Added"
    assert result["previous_version"] == "v0.1.0"
    assert result["release_kind"] == "minor"
    assert runner.calls[0] == TAG_LIST
    assert runner.calls[2] == "claude -p"


def test_the_prompt_goes_on_stdin_not_the_command_line(repo):
    """Shell quoting is not portable, so the prompt must never be an argument.

    shlex.quote produces POSIX single quotes, which cmd.exe passes through as
    ordinary characters; a prompt built into the command arrives on Windows
    shredded into fragments at every space.
    """
    tricky = "abc123 fix: don't \"quote\" me; rm -rf /"
    runner = fake_runner([step("v1.0.0"), step(tricky), step("notes")])
    handle_notes({"repo_path": str(repo), "version": "1.0.1"}, runner=runner)

    assert runner.calls[2] == "claude -p"
    prompt = runner.stdins[2]
    assert tricky in prompt
    assert "1.0.1" in prompt
    assert "patch" in prompt


def test_notes_fall_back_to_the_commit_list_when_claude_fails(repo):
    runner = fake_runner(
        [step("v0.1.0"), step("abc123 fix: a bug"), step("command not found", exit_code=127)]
    )
    result = handle_notes({"repo_path": str(repo), "version": "0.1.1"}, runner=runner)
    assert result["notes_source"] == "git-log"
    assert result["release_notes"] == "## Changes\n\n- abc123 fix: a bug"
    assert result["release_kind"] == "patch"


def test_notes_fall_back_when_claude_answers_with_nothing(repo):
    runner = fake_runner([step("v0.1.0"), step("abc123 fix: a bug"), step("  \n ")])
    result = handle_notes({"repo_path": str(repo), "version": "0.1.1"}, runner=runner)
    assert result["notes_source"] == "git-log"
    assert result["release_notes"] == "## Changes\n\n- abc123 fix: a bug"


def test_a_repository_without_tags_is_a_major_release(repo):
    runner = fake_runner([step("", exit_code=128), step("abc123 chore: first commit"), step("x")])
    result = handle_notes({"repo_path": str(repo), "version": "0.1.0"}, runner=runner)
    assert result["previous_version"] == ""
    assert result["release_kind"] == "major"


def test_an_empty_tag_list_counts_as_no_previous_release(repo):
    runner = fake_runner([step("\n  \n"), step("abc123 chore: first commit"), step("x")])
    result = handle_notes({"repo_path": str(repo), "version": "0.1.0"}, runner=runner)
    assert result["previous_version"] == ""
    assert result["release_kind"] == "major"


def test_a_bumped_patch_number_is_a_patch_release(repo):
    runner = fake_runner([step("v1.2.3"), step("abc123 fix: a bug"), step("x")])
    result = handle_notes({"repo_path": str(repo), "version": "1.2.4"}, runner=runner)
    assert result["release_kind"] == "patch"
    assert result["previous_version"] == "v1.2.3"


def test_the_commit_range_starts_at_the_previous_tag(repo):
    runner = fake_runner([step("v1.2.3"), step("abc123 fix: a bug"), step("x")])
    handle_notes({"repo_path": str(repo), "version": "1.2.4"}, runner=runner)
    assert runner.calls[1] == "git log v1.2.3..HEAD --oneline --no-decorate"


def test_without_a_tag_the_last_commits_are_listed_instead(repo):
    runner = fake_runner([step("", exit_code=128), step("abc123 chore: first commit"), step("x")])
    handle_notes({"repo_path": str(repo), "version": "0.1.0"}, runner=runner)
    assert runner.calls[1] == "git log --oneline --no-decorate -n 50"


def test_notes_survive_a_failing_git_log(repo):
    runner = fake_runner(
        [step("v1.2.3"), step("fatal: bad revision", exit_code=128), step("", exit_code=127)]
    )
    result = handle_notes({"repo_path": str(repo), "version": "1.2.4"}, runner=runner)
    assert result["notes_source"] == "git-log"
    assert result["release_notes"] == "Release v1.2.4."


def test_notes_require_a_version(repo):
    with pytest.raises(HandlerError, match="version"):
        handle_notes({"repo_path": str(repo)}, runner=fake_runner([]))


# ---- the approval timeout default ----------------------------------------


def test_gates_default_the_approval_timeout_when_it_was_not_set(repo):
    result = handle_gates({"repo_path": str(repo)}, runner=fake_runner([0, 0]))
    assert result["approval_timeout"] == DEFAULT_APPROVAL_TIMEOUT


def test_gates_keep_an_approval_timeout_that_was_set_at_start(repo):
    result = handle_gates(
        {"repo_path": str(repo), "approval_timeout": "PT2M"}, runner=fake_runner([0, 0])
    )
    assert result["approval_timeout"] == "PT2M"


# ---- release notes reaching the publish command --------------------------


NOTES_CONFIG = """
gates:
  - name: tests
    run: pytest -q
tag:
  format: "v{version}"
publish:
  run: gh release create v{version} --notes-file {notes_file}
"""


@pytest.fixture()
def notes_repo(tmp_path):
    (tmp_path / "devflows.yaml").write_text(NOTES_CONFIG, encoding="utf-8")
    return tmp_path


def test_publish_writes_the_approved_notes_to_the_file_the_command_asks_for(notes_repo):
    created = StepResult(command="gh", exit_code=0, output="https://x/y", duration_seconds=0.1)
    runner = fake_runner([0, 0, created])
    result = handle_publish(
        {
            "repo_path": str(notes_repo),
            "version": "0.2.0",
            "tag_name": "v0.2.0",
            "dry_run": False,
            "release_notes": "## Added\n- a thing",
        },
        runner=runner,
    )
    command = result["publish_command"]
    assert "--notes-file" in command
    assert "{notes_file}" not in command
    path = Path(command.split("--notes-file ", 1)[1].strip())
    assert path.read_text(encoding="utf-8").startswith("## Added")


def test_publish_writes_a_placeholder_when_there_are_no_notes(notes_repo):
    created = StepResult(command="gh", exit_code=0, output="https://x/y", duration_seconds=0.1)
    result = handle_publish(
        {"repo_path": str(notes_repo), "version": "0.2.0", "tag_name": "v0.2.0", "dry_run": False},
        runner=fake_runner([0, 0, created]),
    )
    path = Path(result["publish_command"].split("--notes-file ", 1)[1].strip())
    assert "Release v0.2.0." in path.read_text(encoding="utf-8")


def test_a_publish_command_without_the_placeholder_writes_no_file(repo):
    created = StepResult(command="gh", exit_code=0, output="https://x/y", duration_seconds=0.1)
    result = handle_publish(
        {
            "repo_path": str(repo),
            "version": "0.1.0",
            "tag_name": "v0.1.0",
            "dry_run": False,
            "release_notes": "ignored",
        },
        runner=fake_runner([0, 0, created]),
    )
    assert result["publish_command"] == "gh release create v0.1.0 --generate-notes"


# ---- undo tag ------------------------------------------------------------


def test_untag_deletes_the_tag_locally_and_on_the_remote(repo):
    runner = fake_runner([0, 0])
    result = handle_untag(
        {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": False},
        runner=runner,
    )
    assert runner.calls == ["git tag -d v0.1.0", "git push origin :refs/tags/v0.1.0"]
    assert result["tag_deleted"] is True


def test_untag_tolerates_a_tag_that_was_never_pushed(repo):
    not_there = StepResult(
        command="git push", exit_code=1, output="remote ref does not exist", duration_seconds=0.1
    )
    result = handle_untag(
        {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": False},
        runner=fake_runner([0, not_there]),
    )
    assert result["tag_deleted"] is True
    assert "remote: not deleted" in result["untag_detail"]


def test_untag_deletes_nothing_in_a_dry_run(repo):
    runner = fake_runner([])
    result = handle_untag(
        {"repo_path": str(repo), "version": "0.1.0", "tag_name": "v0.1.0", "dry_run": True},
        runner=runner,
    )
    assert runner.calls == []
    assert result["tag_deleted"] is False
