"""Answer one question: will a release run on this machine right now?

Run it with `devflows-doctor`. It prints one line per check and exits
non-zero if anything a release needs is missing, so it also works in a script.

Every check reports rather than raises. A doctor that stops at the first
problem makes you run it five times.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from devflows_core.config import ConfigError, load_config
from devflows_core.engine import PROCESS_KEY, EngineClient, EngineError
from devflows_core.steps import run_step

DECISION_KEY = "release-policy"


@dataclass(frozen=True)
class Check:
    """One thing that is either in place or not."""

    name: str
    ok: bool
    detail: str
    required: bool = True


def check_engine(client: EngineClient) -> list[Check]:
    """The engine answers, and it has the process and the decision deployed."""
    status = client.engine_status()
    if not status["reachable"]:
        return [
            Check("engine", False, status["error"] or "not reachable"),
            Check("process deployed", False, "cannot tell, the engine is down"),
            Check("decision deployed", False, "cannot tell, the engine is down"),
        ]

    checks = [Check("engine", True, f"CIB seven {status['version']} at {status['url']}")]

    try:
        processes = {item["key"] for item in client.list_process_definitions()}
        decisions = {item["key"] for item in client.list_decision_definitions()}
    except EngineError as error:
        checks.append(Check("deployments", False, str(error)))
        return checks

    checks.append(
        Check(
            "process deployed",
            PROCESS_KEY in processes,
            PROCESS_KEY if PROCESS_KEY in processes else f"deploy {PROCESS_KEY}",
        )
    )
    checks.append(
        Check(
            "decision deployed",
            DECISION_KEY in decisions,
            DECISION_KEY if DECISION_KEY in decisions else f"deploy {DECISION_KEY}",
        )
    )
    return checks


def check_repository(repo_path: Path) -> list[Check]:
    """The repository has a devflows.yaml that parses."""
    try:
        config = load_config(repo_path)
    except ConfigError as error:
        return [Check("devflows.yaml", False, str(error))]

    gates = ", ".join(gate.name for gate in config.gates)
    return [Check("devflows.yaml", True, f"gates: {gates}")]


def check_tools(repo_path: Path, runner=run_step) -> list[Check]:
    """git and gh are installed, and gh is logged in.

    A missing gh only matters when you actually publish, so it is not required:
    a dry run works without it.
    """
    checks = []

    git = runner("git --version", cwd=repo_path, timeout=30)
    checks.append(Check("git", git.ok, git.output.splitlines()[0] if git.output else "missing"))

    gh = runner("gh auth status", cwd=repo_path, timeout=30)
    checks.append(
        Check(
            "gh authenticated",
            gh.ok,
            "logged in" if gh.ok else "run 'gh auth login' before a real release",
            required=False,
        )
    )

    claude = runner("claude --version", cwd=repo_path, timeout=30)
    checks.append(
        Check(
            "claude CLI",
            claude.ok,
            claude.output.strip() if claude.ok else "notes fall back to the commit list",
            required=False,
        )
    )
    return checks


def run_checks(repo_path: Path) -> list[Check]:
    """Every check, in the order a release needs them."""
    with EngineClient(timeout=5.0) as client:
        checks = check_engine(client)
    checks.extend(check_repository(repo_path))
    checks.extend(check_tools(repo_path))
    return checks


def format_report(checks: list[Check]) -> str:
    """One line per check, aligned, with the failures obvious."""
    width = max(len(check.name) for check in checks)
    lines = []
    for check in checks:
        if check.ok:
            mark = "ok  "
        else:
            mark = "FAIL" if check.required else "warn"
        lines.append(f"[{mark}] {check.name.ljust(width)}  {check.detail}")
    return "\n".join(lines)


def main() -> None:
    """Entry point for the devflows-doctor console script."""
    repo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    checks = run_checks(repo_path)
    print(format_report(checks))

    broken = [check for check in checks if check.required and not check.ok]
    if broken:
        print(f"\n{len(broken)} problem(s) would stop a release.")
        sys.exit(1)
    print("\nReady to release.")


if __name__ == "__main__":
    main()
