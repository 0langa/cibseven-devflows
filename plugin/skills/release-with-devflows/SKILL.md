---
name: release-with-devflows
description: Use when the user wants to cut a release of a repository that has a devflows.yaml - "release this", "cut v1.2.0", "ship it", "run the release process". Drives the release ritual as a BPMN process on the local CIB seven engine, where a DMN table decides whether a human has to approve, and you must never approve on their behalf.
---

# Releasing through cibseven-devflows

The release runs as a BPMN process on a local CIB seven engine. The engine owns the state and the
history; the worker on this machine runs the commands; a decision table decides whether a human is
asked at all.

The process is:

```
gates -> draft release notes -> decide policy (DMN) -> approval required?
    no  -> tag -> publish
    yes -> human approval (with a timer) -> approved? -> tag -> publish
```

If publishing fails after the tag was created, the process compensates and deletes the tag again.

## Before you start

1. Call `doctor(repo_path)`. One call reports the engine, whether the `devflows-release` process
   and the `release-policy` decision are deployed, and whether the repository's `devflows.yaml`
   parses. Read the `checks` list and fix what is not `ok`:
   - engine not reachable: `docker compose -f engine/docker-compose.yml up -d`, wait ~30 seconds.
   - process or decision not deployed: call `deploy_process`.
   - `devflows.yaml` fails to parse: the repository cannot be released this way. Stop.
   Only if `doctor` is unavailable, fall back to `engine_status` plus `list_processes`.
2. The worker. There is no tool for this. If a run makes no progress, the worker is almost always
   the reason: the user must run `uv run devflows-worker` in a second terminal.

## The order to call the tools

1. `list_gates(repo_path)` - show the user what is about to run.
2. `start_release(repo_path, version, dry_run=true)` - **always rehearse first.** Report the
   process instance id and the link to the run in the web UI.
3. `get_run(process_instance_id)` - poll. Show the user the `gates` list, not the raw variables.
   Then read the result carefully, because there are two different outcomes. See below.
4. `get_run` again at the end to report `tag_name`, `release_url` and `state`.
5. Only when the dry run finished cleanly, offer the real run:
   `start_release(repo_path, version, dry_run=false)`.

## A release may not stop for a human at all

The DMN table `release-policy` auto-approves a patch release whose gates are green. A minor or
major release, or a first release with no previous tag, still needs a human.

So do not sit and wait for a task that will never appear. After each `get_run`:

- `state` is `running` and `open_tasks` is empty: the process is still working. Poll again.
- `open_tasks` is not empty: a human is being asked. Go to the next section.
- `state` is not `running` and there are no `open_tasks`: **the run is finished.** Nobody was
  asked. Read `policy.policy_reason` from the variables and tell the user why - for example
  "patch release with green gates, approved by policy". On the auto-approved path there is no
  `approved` variable, because no human said yes. That is expected, not a bug.

## When a human is asked

Stop and ask the user. Show them, in one message:

- the gate report from `gates`,
- the version and whether this is a dry run,
- the drafted `release_notes`, and `notes_source` (`claude` if a local `claude` call wrote them,
  `git-log` if it fell back to the raw commit list).

Show the notes because **whatever is approved becomes the published release body.**

Then wait for an explicit yes and call `approve_gate(task_id, approve, comment)` with their words
as the comment.

`approve_gate` sends only `approved` and `approval_comment`. **It cannot change the release
notes.** If the user wants to edit the text, they must do it in the approval form in the web UI at
<http://localhost:8080/webapp/#/seven/auth/tasks> as `demo` / `demo`, filter **My Group Tasks**.
Say that plainly rather than offering to edit the notes yourself. If they approve in the web UI,
poll `get_run` instead of calling `approve_gate`.

## The approval expires

The approval task carries a timer. `approval_timeout` is an ISO 8601 duration and defaults to
`PT24H`. `start_release` does not expose it, so a run started through this tool always gets the
default; a run started directly against the engine REST API can set it, which is how a short
`PT2M` demo is done.

If a run ended with no `approved` variable **and** no `policy.policy_reason` saying it was
auto-approved, the timer fired: the release was forgotten and rejected itself. Tell the user that,
and offer to start a new run.

## When a run is stuck

`get_run` reports `incidents`. A `failedExternalTask` incident means a command ran out of retries.
The two usual causes:

- the worker is not running, or
- a command in `devflows.yaml` failed three times.

Read the incident message, tell the user the cause, and only once it is fixed call
`retry_run(process_instance_id)` to give the task another attempt.

`cancel_run(process_instance_id, reason)` stops a run that should not continue. Ask first.

## Finding earlier runs

`list_runs(limit)` shows recent runs, newest first, with their state and version. Use it when the
user asks what they released lately, or when they have lost a process instance id.

## Rules

- `dry_run` defaults to true. Never pass `dry_run=false` unless the user asked for a real release
  in this conversation.
- **Never call `approve_gate` on your own judgement.** Always stop and ask the user first, and wait
  for an explicit yes. The approval step is the whole point of putting this in an engine.
- If a gate fails, the process ends at "Gates failed". Show the failing gate's `output` and stop.
  Do not restart the release until the user has fixed the problem.
- If publishing fails, the process deletes the tag again and ends at "Publish failed". The
  repository is left as it was, so a new run can use the same version.
