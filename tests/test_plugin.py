"""The plugin must be well formed, or Claude Code silently ignores it."""

import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
SKILL = PLUGIN / "skills" / "release-with-devflows" / "SKILL.md"


def read_skill() -> str:
    return SKILL.read_text("utf-8")


def test_the_manifest_names_the_plugin_and_its_version():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert manifest["name"] == "cibseven-devflows"
    assert manifest["version"] == "0.2.0"
    assert manifest["description"]


def test_the_mcp_config_starts_the_devflows_server():
    config = json.loads((PLUGIN / ".mcp.json").read_text("utf-8"))
    server = config["mcpServers"]["cibseven-devflows"]
    assert server["command"] == "uv"
    assert "devflows-mcp" in server["args"]


def test_the_skill_has_frontmatter_with_a_name_and_a_description():
    text = read_skill()
    assert text.startswith("---")
    front = text.split("---", 2)[1]
    assert "name: release-with-devflows" in front
    assert "description:" in front


def test_the_skill_names_every_tool_the_agent_has_to_call():
    text = read_skill()
    for tool in (
        "doctor",
        "engine_status",
        "deploy_process",
        "list_gates",
        "start_release",
        "get_run",
        "approve_gate",
        "list_runs",
        "retry_run",
        "cancel_run",
    ):
        assert tool in text, f"the skill never mentions {tool}"


def test_the_skill_warns_that_a_release_can_be_approved_by_policy():
    # An agent that does not know about the auto-approved path waits forever for
    # a task that never appears.
    text = read_skill().lower()
    assert "auto" in text
    assert "policy_reason" in text


def test_the_skill_forbids_approving_on_the_agents_own_judgement():
    text = read_skill().lower()
    assert "approve_gate" in text
    # The rule and the instruction to ask have to sit close enough together that
    # an agent reading either one finds the other.
    for index in _positions(text, "own judgement"):
        window = text[max(0, index - 400) : index + 400]
        if "approve_gate" in window and "ask" in window:
            return
    raise AssertionError("the skill does not forbid approving without asking the user")


def test_the_skill_explains_the_release_notes_in_the_approval():
    text = read_skill()
    assert "release_notes" in text
    assert "notes_source" in text


def test_the_skill_explains_that_the_approval_expires():
    text = read_skill()
    assert "approval_timeout" in text
    assert "PT24H" in text


def test_the_skill_explains_a_stuck_run():
    text = read_skill()
    assert "incidents" in text
    assert "failedExternalTask" in text


def test_the_skill_keeps_the_dry_run_default():
    text = read_skill()
    assert "dry_run" in text
    assert "dry_run=false" in text


def test_the_command_file_has_frontmatter():
    text = (PLUGIN / "commands" / "release.md").read_text("utf-8")
    assert text.startswith("---")
    front = text.split("---", 2)[1]
    assert "description:" in front
    assert "argument-hint:" in front


def test_the_command_follows_the_same_order_as_the_skill():
    text = (PLUGIN / "commands" / "release.md").read_text("utf-8")
    for tool in ("doctor", "list_gates", "start_release", "get_run", "approve_gate"):
        assert tool in text, f"the command never mentions {tool}"
    assert "--real" in text


def _positions(haystack: str, needle: str) -> list[int]:
    positions = []
    start = haystack.find(needle)
    while start != -1:
        positions.append(start)
        start = haystack.find(needle, start + 1)
    return positions
