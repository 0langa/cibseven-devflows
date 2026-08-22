---
name: release-with-devflows
description: Use when the user wants to cut a release of a repository that has a devflows.yaml - "release this", "cut v1.2.0", "ship it", "run the release process". Drives the release ritual as a BPMN process on the local CIB seven engine, with a human approval step that you must not skip.
---

# Releasing through cibseven-devflows

The release runs as a BPMN process on a local CIB seven engine. The engine owns the state and the
history; the worker on this machine runs the commands; a human approves in the middle.

## Before you start

The user must have three things running. Check, do not assume.

1. The engine. Call `engine_status`. If it is not reachable, tell the user to run
   `docker compose -f engine/docker-compose.yml up -d` and wait about 30 seconds.
2. The worker. There is no tool for this. If a run gets stuck with no progress, the worker is
   almost always the reason: the user must run `uv run devflows-worker` in a second terminal.
3. The process. Call `list_processes`. If `devflows-release` is missing, call `deploy_process`.

## The order to call the tools

1. `list_gates(repo_path)` - show the user what is about to run. If this fails, the repository has
   no `devflows.yaml` and cannot be released this way.
2. `start_release(repo_path, version, dry_run=true)` - **always rehearse first.** Report the
   process instance id and the Cockpit link.
3. `get_run(process_instance_id)` - poll until `state` is no longer `running` or `open_tasks` is not
   empty. Show the user the `gates` list, not the raw variables.
4. When a task is waiting, **stop and ask the user**. Do not call `approve_gate` on your own
   judgement. Show them the gate results and the version, and wait for an explicit yes.
5. `approve_gate(task_id, approve, comment)` - only after the user said yes. Pass their words as
   the comment.
6. `get_run` again to report the outcome: `tag_name`, `release_url`, `state`.
7. Only when the dry run finished cleanly, offer the real run:
   `start_release(repo_path, version, dry_run=false)`, and go through the same approval again.

## Rules

- `dry_run` defaults to true. Never pass `dry_run=false` unless the user asked for a real release
  in this conversation.
- Never approve on the user's behalf. The approval step is the whole point of putting this in an
  engine.
- The user can also approve in Tasklist at
  <http://localhost:8080/camunda/app/tasklist/default/> as `demo` / `demo`.
  If they prefer that, wait and poll `get_run` instead of calling `approve_gate`.
- If a gate fails, the process ends at "Gates failed". Show the failing gate's `output` and stop.
  Do not restart the release until the user has fixed the problem.
