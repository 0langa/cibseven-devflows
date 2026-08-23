"""The devflows MCP server.

Run it with `devflows-mcp`. It speaks MCP over stdio, so any MCP client can use
it; the Claude Code plugin in plugin/ is only a thin wrapper around this.

MCPServer is what the official MCP Python SDK 2.0 calls the class that was
named FastMCP in 1.x. The decorator API is the same.

Each tool opens a short-lived engine client. Nothing is cached between calls,
because the engine may be restarted between them.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from devflows_core.engine import EngineClient
from devflows_mcp import __version__, tools

mcp = MCPServer("cibseven-devflows", version=__version__)


@mcp.tool()
def engine_status() -> dict[str, Any]:
    """Check that the local CIB seven engine is reachable and report its version."""
    with EngineClient() as client:
        return tools.engine_status(client)


@mcp.tool()
def deploy_process(bpmn_path: str | None = None) -> dict[str, Any]:
    """Deploy the release process to the engine. Deploying it twice is harmless."""
    with EngineClient() as client:
        return tools.deploy_process(client, bpmn_path)


@mcp.tool()
def list_processes() -> dict[str, Any]:
    """List the process definitions the engine currently knows about."""
    with EngineClient() as client:
        return tools.list_processes(client)


@mcp.tool()
def start_release(
    repo_path: str,
    version: str,
    dry_run: bool = True,
    approval_timeout: str = "PT24H",
) -> dict[str, Any]:
    """Start a release run for a repository.

    Runs the gates, drafts release notes, then asks the policy whether a human
    is needed. With dry_run true, which is the default, nothing is tagged or
    published. approval_timeout is an ISO 8601 duration after which an
    unanswered approval expires.
    """
    with EngineClient() as client:
        return tools.start_release(client, repo_path, version, dry_run, approval_timeout)


@mcp.tool()
def get_run(process_instance_id: str) -> dict[str, Any]:
    """Report the state, the current activity, the gate report and the variables of a run."""
    with EngineClient() as client:
        return tools.get_run(client, process_instance_id)


@mcp.tool()
def list_gates(repo_path: str) -> dict[str, Any]:
    """List the gates a release of this repository would run. Does not touch the engine."""
    return tools.list_gates(repo_path)


@mcp.tool()
def approve_gate(task_id: str, approve: bool, comment: str = "") -> dict[str, Any]:
    """Approve or reject a waiting release. This is the human decision in the process."""
    with EngineClient() as client:
        return tools.approve_gate(client, task_id, approve, comment)


@mcp.tool()
def list_runs(limit: int = 10) -> dict[str, Any]:
    """List the most recent release runs, newest first, with their state."""
    with EngineClient() as client:
        return tools.list_runs(client, limit)


@mcp.tool()
def retry_run(process_instance_id: str) -> dict[str, Any]:
    """Give a run that is stuck on an incident another attempt."""
    with EngineClient() as client:
        return tools.retry_run(client, process_instance_id)


@mcp.tool()
def cancel_run(
    process_instance_id: str,
    reason: str = "cancelled through the devflows MCP server",
) -> dict[str, Any]:
    """Stop a running release. The reason is kept in the engine history."""
    with EngineClient() as client:
        return tools.cancel_run(client, process_instance_id, reason)


@mcp.tool()
def doctor(repo_path: str | None = None) -> dict[str, Any]:
    """Check whether a release can run: engine, process, decision, config."""
    with EngineClient() as client:
        return tools.doctor(client, repo_path)


def main() -> None:
    """Entry point for the devflows-mcp console script."""
    mcp.run()


if __name__ == "__main__":
    main()
