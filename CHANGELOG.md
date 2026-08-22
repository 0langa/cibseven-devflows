# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-22

First release. It was cut by running this project's own release process.

### Added

- `processes/release.bpmn`: the release ritual as a BPMN 2.0 process with three external tasks,
  one user approval task and two exclusive gateways.
- `devflows_core`: the CIB seven REST client, the `devflows.yaml` parser and the shell step runner.
- `devflows_worker`: an external task worker for the topics `devflows.gates`, `devflows.tag` and
  `devflows.publish`, with `dry_run` support. Console script `devflows-worker`.
- `devflows_mcp`: a stdio MCP server with the tools `engine_status`, `deploy_process`,
  `list_processes`, `start_release`, `get_run`, `list_gates` and `approve_gate`. Console script
  `devflows-mcp`.
- `plugin/`: a Claude Code plugin with the `release-with-devflows` skill and the
  `/devflows:release` command.
- `engine/docker-compose.yml`: a local CIB seven 2.2.0 engine with a persistent H2 volume, and a
  one-shot init service so a cold `up -d` works without manual steps.
- Unit tests using `httpx.MockTransport`, and integration tests that drive the real process against
  a real engine and skip when no engine is running.
- GitHub Actions CI running `ruff check` and `pytest`.

### Notes

- The MCP server targets version 2.0 of the official MCP Python SDK, where the class formerly known
  as `FastMCP` is `mcp.server.mcpserver.MCPServer`.

[0.1.0]: https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0
