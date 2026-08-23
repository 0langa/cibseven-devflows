"""The MCP server registers exactly the seven tools, with usable descriptions."""

import asyncio

from devflows_mcp.server import mcp

EXPECTED_TOOLS = {
    "engine_status",
    "deploy_process",
    "list_processes",
    "start_release",
    "get_run",
    "list_gates",
    "approve_gate",
    "list_runs",
    "retry_run",
    "cancel_run",
    "doctor",
}


def registered_tools():
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def test_the_server_registers_exactly_the_expected_tools():
    assert set(registered_tools()) == EXPECTED_TOOLS


def test_every_tool_has_a_description():
    for name, tool in registered_tools().items():
        assert tool.description, f"{name} has no description"


def test_start_release_declares_its_three_arguments():
    schema = registered_tools()["start_release"].input_schema
    assert set(schema["properties"]) == {"repo_path", "version", "dry_run"}
    assert set(schema["required"]) == {"repo_path", "version"}


def test_approve_gate_declares_its_arguments():
    schema = registered_tools()["approve_gate"].input_schema
    assert set(schema["properties"]) == {"task_id", "approve", "comment"}


def test_the_server_is_named_after_the_project():
    assert mcp.name == "cibseven-devflows"


def test_the_server_reports_its_version():
    from devflows_mcp import __version__

    assert mcp.version == __version__
