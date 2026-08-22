"""The plugin must be well formed, or Claude Code silently ignores it."""

import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


def test_the_manifest_names_the_plugin_and_its_version():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert manifest["name"] == "cibseven-devflows"
    assert manifest["version"] == "0.1.0"
    assert manifest["description"]


def test_the_mcp_config_starts_the_devflows_server():
    config = json.loads((PLUGIN / ".mcp.json").read_text("utf-8"))
    server = config["mcpServers"]["cibseven-devflows"]
    assert server["command"] == "uv"
    assert "devflows-mcp" in server["args"]


def test_the_skill_has_frontmatter_with_a_name_and_a_description():
    text = (PLUGIN / "skills" / "release-with-devflows" / "SKILL.md").read_text("utf-8")
    assert text.startswith("---")
    front = text.split("---", 2)[1]
    assert "name: release-with-devflows" in front
    assert "description:" in front


def test_the_skill_names_every_tool_the_agent_has_to_call():
    text = (PLUGIN / "skills" / "release-with-devflows" / "SKILL.md").read_text("utf-8")
    for tool in (
        "engine_status",
        "deploy_process",
        "list_gates",
        "start_release",
        "get_run",
        "approve_gate",
    ):
        assert tool in text


def test_the_command_file_has_frontmatter():
    text = (PLUGIN / "commands" / "release.md").read_text("utf-8")
    assert text.startswith("---")
    assert "description:" in text.split("---", 2)[1]
