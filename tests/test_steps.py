"""Running one shell command and reporting what happened."""

import sys

from devflows_core.steps import (
    MAX_OUTPUT_CHARS,
    StepResult,
    run_step,
    trim_output,
)


def test_successful_command_reports_exit_code_zero(tmp_path):
    result = run_step(f'{sys.executable} -c "print(\'hello\')"', cwd=tmp_path)
    assert isinstance(result, StepResult)
    assert result.exit_code == 0
    assert result.ok is True
    assert result.timed_out is False
    assert "hello" in result.output


def test_failing_command_reports_a_non_zero_exit_code(tmp_path):
    result = run_step(f'{sys.executable} -c "import sys; sys.exit(3)"', cwd=tmp_path)
    assert result.exit_code == 3
    assert result.ok is False


def test_stderr_is_captured_too(tmp_path):
    command = f'{sys.executable} -c "import sys; sys.stderr.write(\'boom\')"'
    result = run_step(command, cwd=tmp_path)
    assert "boom" in result.output


def test_command_runs_in_the_given_directory(tmp_path):
    marker = tmp_path / "marker.txt"
    marker.write_text("found me", encoding="utf-8")
    command = f'{sys.executable} -c "print(open(\'marker.txt\').read())"'
    result = run_step(command, cwd=tmp_path)
    assert "found me" in result.output


def test_timeout_is_reported_and_not_raised(tmp_path):
    command = f'{sys.executable} -c "import time; time.sleep(5)"'
    result = run_step(command, cwd=tmp_path, timeout=1)
    assert result.timed_out is True
    assert result.ok is False
    assert "timed out" in result.output.lower()


def test_duration_is_recorded(tmp_path):
    result = run_step(f'{sys.executable} -c "pass"', cwd=tmp_path)
    assert result.duration_seconds >= 0.0


def test_output_is_trimmed_before_it_reaches_the_engine(tmp_path):
    command = f'{sys.executable} -c "print(\'x\' * 20000)"'
    result = run_step(command, cwd=tmp_path)
    assert len(result.output) <= MAX_OUTPUT_CHARS + 200


def test_trim_output_keeps_short_text_unchanged():
    assert trim_output("short") == "short"


def test_trim_output_keeps_the_head_and_the_tail():
    text = "A" * 100 + "B" * 100
    trimmed = trim_output(text, limit=60)
    assert trimmed.startswith("A")
    assert trimmed.endswith("B")
    assert "trimmed" in trimmed


def test_stdin_reaches_the_command(tmp_path):
    # Long or awkward text belongs on stdin: shell quoting is not portable.
    command = f'{sys.executable} -c "import sys; sys.stdout.write(sys.stdin.read().upper())"'
    result = run_step(command, cwd=tmp_path, stdin="hello from stdin")
    assert "HELLO FROM STDIN" in result.output


def test_a_command_without_stdin_still_works(tmp_path):
    result = run_step(f'{sys.executable} -c "print(1)"', cwd=tmp_path)
    assert result.ok
