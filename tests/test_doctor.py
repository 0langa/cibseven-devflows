"""The doctor answers one question, and never stops at the first problem."""

import httpx
import pytest

from devflows_core.doctor import (
    Check,
    check_engine,
    check_repository,
    check_tools,
    format_report,
)
from devflows_core.engine import EngineClient
from devflows_core.steps import StepResult

CONFIG = """
gates:
  - name: tests
    run: pytest -q
  - name: lint
    run: ruff check .
publish:
  run: gh release create v{version}
"""


def client_for(handler):
    return EngineClient(transport=httpx.MockTransport(handler))


def healthy(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/version"):
        return httpx.Response(200, json={"version": "2.2.0"})
    if path.endswith("/engine"):
        return httpx.Response(200, json=[{"name": "default"}])
    if path.endswith("/process-definition"):
        return httpx.Response(200, json=[{"key": "devflows-release", "id": "a", "version": 3}])
    if path.endswith("/decision-definition"):
        return httpx.Response(200, json=[{"key": "release-policy", "id": "b", "version": 1}])
    return httpx.Response(200, json=[])


def named(checks):
    return {check.name: check for check in checks}


def test_a_healthy_engine_passes_all_three_engine_checks():
    checks = named(check_engine(client_for(healthy)))
    assert checks["engine"].ok
    assert checks["process deployed"].ok
    assert checks["decision deployed"].ok


def test_an_unreachable_engine_fails_every_engine_check_at_once():
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    checks = check_engine(client_for(refused))
    # All three, not just the first: one run should tell you everything.
    assert len(checks) == 3
    assert not any(check.ok for check in checks)


def test_a_missing_process_is_named():
    def without_process(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/process-definition"):
            return httpx.Response(200, json=[])
        return healthy(request)

    checks = named(check_engine(client_for(without_process)))
    assert checks["process deployed"].ok is False
    assert "devflows-release" in checks["process deployed"].detail
    assert checks["decision deployed"].ok is True


def test_a_valid_repository_lists_its_gates(tmp_path):
    (tmp_path / "devflows.yaml").write_text(CONFIG, encoding="utf-8")
    check = check_repository(tmp_path)[0]
    assert check.ok
    assert "tests" in check.detail and "lint" in check.detail


def test_a_repository_without_a_config_fails(tmp_path):
    check = check_repository(tmp_path)[0]
    assert check.ok is False
    assert "devflows.yaml" in check.detail


def fake_runner(results):
    def runner(command, cwd, timeout=900):
        exit_code, output = results.get(command.split()[0], (0, "fine"))
        return StepResult(
            command=command, exit_code=exit_code, output=output, duration_seconds=0.1
        )

    return runner


def test_git_is_required_but_gh_and_claude_are_not(tmp_path):
    checks = named(check_tools(tmp_path, runner=fake_runner({})))
    assert checks["git"].required is True
    assert checks["gh authenticated"].required is False
    assert checks["claude CLI"].required is False


def test_a_missing_gh_login_is_a_warning_not_a_failure(tmp_path):
    runner = fake_runner({"gh": (1, "not logged in")})
    checks = named(check_tools(tmp_path, runner=runner))
    assert checks["gh authenticated"].ok is False
    assert checks["gh authenticated"].required is False
    assert "gh auth login" in checks["gh authenticated"].detail


def test_a_missing_claude_says_what_happens_instead(tmp_path):
    runner = fake_runner({"claude": (127, "command not found")})
    checks = named(check_tools(tmp_path, runner=runner))
    assert "commit list" in checks["claude CLI"].detail


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        (Check("engine", True, "up"), "[ok  ]"),
        (Check("engine", False, "down"), "[FAIL]"),
        (Check("claude CLI", False, "missing", required=False), "[warn]"),
    ],
)
def test_the_report_distinguishes_a_failure_from_a_warning(check, expected):
    assert format_report([check]).startswith(expected)


def test_the_report_aligns_the_names():
    report = format_report([Check("a", True, "x"), Check("bbbbb", True, "y")])
    first, second = report.splitlines()
    assert first.index("x") == second.index("y")
