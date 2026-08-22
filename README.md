# cibseven-devflows

Run your own developer workflows (release rituals, quality gates, cleanup jobs) as BPMN processes on [CIB seven](https://cibseven.org), the open-source BPM engine, and drive them from AI coding agents such as Claude Code.

## Status

Design phase. Nothing runnable yet. The design document will live in `docs/superpowers/specs/`.

## Planned shape

- `engine/` – Docker Compose setup for a local CIB seven engine
- `processes/` – BPMN diagrams for developer workflows
- `workers/` – Python external-task workers that execute the process steps
- `plugin/` – Claude Code plugin (MCP server + skills) that talks to the engine REST API

## Requirements

- Docker Desktop (WSL 2 backend)
- Python 3.12+ and [uv](https://github.com/astral-sh/uv)
- Camunda Modeler 5.x for editing BPMN diagrams (optional)

## License

Apache License 2.0. See [LICENSE](LICENSE).
