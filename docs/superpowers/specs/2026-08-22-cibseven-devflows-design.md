# cibseven-devflows v0.1.0 — Design

Date: 2026-08-22
Status: Approved

## Problem

Cutting a release is a ritual: run the quality gates, look at the result, decide, tag, publish.
Today that ritual lives in a person's head and in a scrollback buffer. Nothing records that the
gates ran, that a human approved, or what was published. An AI coding agent that offers to "do the
release" has no place to stop and ask.

`cibseven-devflows` moves the ritual into a BPMN process on a local [CIB seven](https://cibseven.org)
engine. The engine owns the state, the history and the wait-for-a-human step. Python external-task
workers do the actual work on the developer's machine. An MCP server lets Claude Code (or any MCP
client) start a run, watch it, and approve it.

The v0.1.0 target is deliberately self-referential: this repository releases itself through its own
process.

## Scope

In scope for v0.1.0:

- One process: the release ritual of a repository.
- One config format: `devflows.yaml` in the target repository.
- One engine: CIB seven 2.2.0 in Docker with H2, on `http://localhost:8080`.
- One agent surface: a stdio MCP server plus a thin Claude Code plugin.

Out of scope for v0.1.0: more processes, remote or multi-user engines, engine authentication,
scheduling, retries with backoff policies, and any cloud service.

## Architecture

```
Claude Code  ──stdio──▶  devflows_mcp  ──REST──▶  CIB seven engine (Docker, H2)
                                                        │
Tasklist web UI  ──────────────────────────────────────▶│  (human approval)
                                                        │
                          devflows_worker  ◀──fetchAndLock──┘
                                 │
                                 └──▶  subprocess in repo_path (pytest, ruff, git, gh)
```

The engine never runs a shell command and never touches the repository. It only holds process
state and hands out work. All side effects happen in the worker, on the developer's machine, in the
directory named by the `repo_path` process variable.

### Python packages

Three packages in one repository, one `pyproject.toml`, one virtual environment:

| Package | Directory | Responsibility |
| --- | --- | --- |
| `devflows_core` | `core/devflows_core/` | Engine REST client, `devflows.yaml` parsing, shell step runner |
| `devflows_worker` | `workers/devflows_worker/` | fetch-and-lock loop and the three topic handlers |
| `devflows_mcp` | `mcp/devflows_mcp/` | stdio MCP server exposing seven tools |

`devflows_core` exists so that the worker and the MCP server can share the REST client and the
config parser without either depending on the other. Both of them import `devflows_core`; neither
imports the other.

Console entry points: `devflows-worker` and `devflows-mcp`.

### Dependencies

`httpx`, `pyyaml`, `mcp`. Development only: `pytest`, `ruff`.

The MCP server uses the official `mcp` package rather than the separate `fastmcp` distribution.
That is one dependency fewer and it is the reference implementation of the protocol.

Version 2.0 of that SDK renamed `FastMCP` to `MCPServer` and moved it from `mcp.server.fastmcp` to
`mcp.server.mcpserver`; the decorator API is unchanged. This project uses the 2.0 name and pins
`mcp>=2.0`, rather than pinning below 2 to keep a removed import path alive.

Engine calls are tested with `httpx.MockTransport`, so no HTTP mocking library is needed.

## The release process

Process key `devflows-release`, `camunda:historyTimeToLive="P30D"`.

```
(start)
   │
   ▼
[run gates]            external task, topic devflows.gates
   │
   ▼
<gates passed?>        exclusive gateway on ${gates_passed}
   ├── no  ─▶ (end: gates failed)
   ▼ yes
[Approve release]      user task, candidateGroups camunda-admin
   │
   ▼
<approved?>            exclusive gateway on ${approved}
   ├── no  ─▶ (end: rejected)
   ▼ yes
[tag]                  external task, topic devflows.tag
   │
   ▼
[publish]              external task, topic devflows.publish
   │
   ▼
(end: released)
```

### Process variables

Set when the instance starts:

| Variable | Type | Meaning |
| --- | --- | --- |
| `repo_path` | String | Absolute path of the repository to release |
| `version` | String | Version without the tag prefix, for example `0.1.0` |
| `dry_run` | Boolean | When true, nothing is tagged or published for real |

Written back by the steps:

| Variable | Type | Written by | Meaning |
| --- | --- | --- | --- |
| `gates_passed` | Boolean | `run gates` | True only if every gate exited 0 |
| `gates_report` | String (JSON) | `run gates` | One entry per gate: name, command, exit code, duration, trimmed output |
| `approved` | Boolean | `Approve release` | The human's decision |
| `approval_comment` | String | `Approve release` | Free text from the approver |
| `tag_name` | String | `tag` | The tag that was created, for example `v0.1.0` |
| `release_url` | String | `publish` | URL of the GitHub Release, or a dry-run placeholder |

### The approval step

The user task carries `camunda:candidateGroups="camunda-admin"` and no assignee. The `demo` user is
a member of `camunda-admin`, so the task appears in the Tasklist filter "My Group Tasks". The
demonstration is: claim the task, read the gate report, tick approve, submit.

The form is a Camunda 7 generated task form built from `camunda:formField` extension elements:
a boolean `approved` and a string `approval_comment`. No separate form file has to be deployed.

The MCP tool `approve_gate` completes the same task over REST. Camunda 7 allows completing an
unassigned task, so the tool works whether or not the task was claimed in the web UI.

## `devflows.yaml`

The file lives in the repository being released and defines what each step runs.

```yaml
gates:
  - name: tests
    run: uv run pytest -q
  - name: lint
    run: uv run ruff check .

tag:
  format: "v{version}"

publish:
  run: gh release create v{version} --generate-notes
```

Rules:

- `gates` is a list; every entry needs `name` and `run`. An empty or missing list is a
  configuration error, not a silently passing run.
- `tag.format` is a Python format string; the only placeholder is `{version}`.
- `publish.run` is a shell command; the only placeholder is `{version}`.
- Unknown top-level keys are ignored, so later versions can add steps without breaking old files.

Parsing produces a typed `DevflowsConfig` object. A malformed file raises `ConfigError` with the
path and the reason, and the worker fails the external task with that message rather than crashing.

## Step execution

One function runs every shell step:

```python
run_step(command: str, cwd: Path, timeout: int) -> StepResult
```

It uses `subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True,
timeout=timeout)` and returns the exit code, stdout, stderr and the elapsed time. Output is trimmed
to a bounded length before it goes into a process variable, so a chatty test run cannot bloat the
engine database.

`shell=True` is deliberate. The commands are the ones already written in the repository's own
`devflows.yaml`, they run as the developer on the developer's machine, and they are the same
commands the developer would type. The engine is bound to localhost and has no authentication;
this is a local developer tool, not a shared service. Both facts are stated plainly in the README.

## Dry run

`dry_run=true` changes the behaviour of the mutating steps only:

- `run gates` always executes for real. A dry run that skipped the tests would be worthless.
- `tag` reports the tag it would create and creates nothing.
- `publish` reports the command it would run, pushes nothing, and sets `release_url` to a
  placeholder that says it was a dry run.

Every step records `dry_run` in its result so the history shows which kind of run it was.

## Worker

`devflows-worker` is a loop:

1. `POST /external-task/fetchAndLock` with the three topics, a long poll, and a lock duration.
2. For each fetched task, dispatch on `topicName` to a handler.
3. On success, `POST /external-task/{id}/complete` with the result variables.
4. On a handled failure (bad config, non-zero gate, missing `gh`), `POST /external-task/{id}/failure`
   with an error message and the trimmed output as details.
5. Repeat until interrupted.

Handlers are plain functions from `(variables, config) -> dict of result variables`. They do not
know about HTTP, which is what makes them easy to test.

Configuration comes from the environment: `DEVFLOWS_ENGINE_URL`
(default `http://localhost:8080/engine-rest`), `DEVFLOWS_WORKER_ID`, lock duration, and the step
timeout. The worker starts with no arguments.

## MCP server

`devflows-mcp` speaks MCP over stdio and exposes seven tools:

| Tool | Arguments | Returns |
| --- | --- | --- |
| `engine_status` | — | Engine reachable, version, engine name |
| `deploy_process` | `bpmn_path` (optional) | Deployment id and the deployed process definition key |
| `list_processes` | — | Deployed process definitions with key, version and id |
| `start_release` | `repo_path`, `version`, `dry_run` | Process instance id |
| `get_run` | `process_instance_id` | State, current activity, and all result variables so far |
| `list_gates` | `repo_path` (optional) | The gates defined in that repository's `devflows.yaml` |
| `approve_gate` | `task_id`, `approve`, `comment` | Confirmation that the task was completed |

`get_run` looks in the runtime API first and falls back to the history API once the instance has
finished, so it answers for both running and completed runs.

Every tool returns a plain dictionary. Engine errors are turned into a readable message rather than
a stack trace, because the caller is a language model that has to explain the failure to a human.

## Claude Code plugin

`plugin/` contains:

- `.claude-plugin/plugin.json` — name `cibseven-devflows`, version, description.
- `.mcp.json` — starts `devflows-mcp` through `uv run`.
- `skills/release-with-devflows/SKILL.md` — when to use the engine for a release and in what order
  to call the tools: check the engine, deploy if needed, start a dry run, read the gate report,
  ask the human, then the real run.
- `commands/release.md` — the `/devflows:release` command.

The MCP server must also work without the plugin, from any MCP client, by running `devflows-mcp`.

## Engine setup

`engine/docker-compose.yml` runs `cibseven/cibseven:latest`, maps port 8080, and mounts a named
volume at `/camunda/camunda-h2-dbs`, which is where the image keeps `process-engine.mv.db`. Without
that volume the history disappears on every restart, and the history is the point.

`engine/README.md` covers `up -d`, `down`, where the web apps and the REST API are, the `demo`
login, and a note that the Docker CLI on this machine lives at
`C:\Users\Julius\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe` and may not be on
`PATH`.

## Testing

Unit tests, no engine required:

- Config parsing: valid file, missing file, malformed YAML, missing keys, empty gate list.
- Step runner: exit code, captured output, timeout, output trimming.
- Gate handler: all pass, one fails, report shape.
- Tag and publish handlers: real mode builds the right command, dry run mutates nothing.
- Engine client: request shape and error translation, using `httpx.MockTransport`.
- Each MCP tool against a mocked engine.

Integration tests in `tests/integration/`, guarded by a module-level fixture that pings
`GET /engine-rest/engine` and calls `pytest.skip` when it fails: deploy the BPMN, start an instance
with `dry_run=true`, let the worker complete it, and assert the history shows a completed instance
with the expected variables.

CI runs `uv sync`, `uv run ruff check .` and `uv run pytest` on `ubuntu-latest`. No engine, so only
the unit tests run there; the integration module skips itself.

## Documentation

- `README.md` — what it is, why, the architecture as a Mermaid diagram, a quickstart of under ten
  commands, and a demo walkthrough.
- `CHANGELOG.md` — Keep a Changelog format, one `0.1.0` entry.
- `docs/DEMO.md` — a five-minute interview demo script: cold start to finished release, plus
  talking points on CIB seven as a Camunda 7 fork, the external task pattern, human-in-the-loop
  approval, and how this relates to CIB seven 2.2's AI agent connector and MCP support.

## Risks

| Risk | Mitigation |
| --- | --- |
| The self-release can only be run once, and a failure leaves a half-published tag | Rehearse with `dry_run=true` first; the tag step is the last reversible point and a bad tag can be deleted locally and remotely |
| `gh` not authenticated when `publish` runs | `publish` checks `gh auth status` first and fails the task with a clear message instead of a confusing CLI error |
| Long test output bloats the H2 database | Output is trimmed before it becomes a process variable |
| The engine is unauthenticated on localhost | Documented plainly; the project is local-first by design and binds to localhost only |
| Docker CLI is not on `PATH` on the development machine | Recorded in `engine/README.md` with the full path |

## Success criteria

- `uv run pytest` green and `uv run ruff check .` clean.
- CI green on GitHub.
- `docker compose -f engine/docker-compose.yml up -d`, then `devflows-worker`, then `devflows-mcp`,
  all start with no manual edits.
- `https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0` exists and was created by the
  process, and Cockpit history shows the completed instance.
- `docs/DEMO.md` takes a reader from a cold start to a finished demo in under ten minutes.
