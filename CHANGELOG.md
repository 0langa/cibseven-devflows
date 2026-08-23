# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed

- The approval form no longer flattens the drafted release notes. It carried a `release_notes`
  string field defaulting to the draft, and a generated form renders a string field as a
  single-line input, so submitting it replaced multi-line markdown with one long line. The field is
  now `notes_override`, empty by default.
- Only what the model puts between `<notes>` markers is published. Replies had arrived wrapped in a
  code fence, with a sentence of preamble, and with a question afterwards, all of which reached the
  release body.
- The model is no longer asked to write notes when there are no commits to summarise, because it
  answers with a question rather than notes.

## [0.2.0] - 2026-08-22

Four things a shell script cannot do.

### Added

- **A decision that lives outside the code.** `processes/release-policy.dmn` is a DMN table that
  decides whether a release needs a human at all. A patch release whose gates are green is approved
  by policy; anything else asks a person. The rule is data, editable in Camunda Modeler.
- **AI-drafted release notes.** A new `devflows.notes` external task collects the commits since the
  previous tag and asks the local `claude` CLI for markdown notes. The draft appears in the approval
  form as an editable field, and whatever is approved becomes the release body. Falls back to the
  commit list when `claude` is not installed; `notes_source` records which happened.
- **Compensation.** If publishing fails after the tag was created, an error boundary event throws
  BPMN compensation and the new `devflows.untag` handler deletes the tag locally and on the remote.
  A failed release leaves nothing behind.
- **An approval that expires.** A boundary timer on the approval task ends a release nobody
  answered. The duration is the `approval_timeout` variable, an ISO 8601 duration defaulting to
  `PT24H`.
- **Retries with backoff.** A step that fails is now retried after 5 s, 15 s and 60 s before an
  incident appears, instead of raising one on the first failure.
- **`devflows-doctor`**, a third console script that checks the engine, the deployed process and
  decision, `devflows.yaml`, `git`, `gh` and `claude`, and reports every result rather than stopping
  at the first problem.
- Four more MCP tools: `list_runs`, `retry_run`, `cancel_run` and `doctor`. `get_run` now reports
  the incidents behind a stuck run.
- `devflows_core.versions.classify_release`, which compares a candidate version against the newest
  tag to decide whether a release is major, minor or patch.

### Changed

- The worker distinguishes a technical failure, which is retried, from a business error, which is
  raised to the engine as a BPMN error with the code `PUBLISH_FAILED` for the diagram to handle.
  A refused publish is no longer an incident, because nothing is broken.
- `publish.run` in `devflows.yaml` accepts a `{notes_file}` placeholder. This repository uses it.

### Fixed

- The integration tests no longer fail when a real `devflows-worker` is running against the same
  engine. They now wait for the state the engine reaches, not for their own poll to be the one that
  caused it.
- Every link points at the CIB seven web UI under `/webapp/`. The older Camunda webapps under
  `/camunda/app/` still work in CIB seven 2.2 but display a deprecation banner.

### Documentation

- `docs/DEMO.md` records the process instance that cut v0.1.0, so the self-release claim can be
  checked.

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

[0.2.0]: https://github.com/0langa/cibseven-devflows/releases/tag/v0.2.0
[0.1.0]: https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0
