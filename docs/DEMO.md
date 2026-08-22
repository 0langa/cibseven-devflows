# Five-minute demo

A cold start to a finished release in under ten minutes, and a five-minute script to run in front
of someone.

## Before the demo

Run these in order. The whole block takes about three minutes, most of it waiting for the engine.

**1. Start the engine.**

```bash
docker compose -f engine/docker-compose.yml up -d
```

Wait until this answers `{"version":"2.2.0"}`. It takes about 40 seconds on a cold start.

```bash
curl -s http://localhost:8080/engine-rest/version
```

**2. Install the project.**

```bash
uv sync
```

**3. Deploy the process.**

```bash
curl -s -X POST http://localhost:8080/engine-rest/deployment/create -F "deployment-name=cibseven-devflows" -F "release.bpmn=@processes/release.bpmn"
```

**4. Start the worker in its own terminal and leave it visible.**

```bash
uv run devflows-worker
```

It should print `Waiting for work on: devflows.gates, devflows.tag, devflows.publish`. Put this
terminal where the audience can see it; it is the part that shows the work actually happening.

**5. Open two browser tabs**, both logged in at <http://localhost:8080/webapp/> as `demo` / `demo`:

- **Processes**: <http://localhost:8080/webapp/#/seven/auth/processes/list> , on `Release ritual`
- **Tasks**: <http://localhost:8080/webapp/#/seven/auth/tasks> , with the filter **My Group Tasks** selected

Use this front-end, not the older webapps under `/camunda/app/`. CIB seven 2.2 still serves
those, but it shows a red banner on every page saying they are deprecated and no longer
supported. Demonstrating the deprecated UI to someone who works on CIB seven would be a poor
look.

**6. Have Claude Code open** in this repository, with the plugin loaded.

## The script

### 0:00 – 0:45 · What this is

> CIB seven is an open-source fork of the Camunda 7 BPM engine, maintained by CIB. This project
> takes a thing I do by hand every week, cutting a release, and runs it as a BPMN process on it.
>
> A release is a process: run the tests, look at them, decide, tag, publish. It has a human
> decision in the middle. That is exactly the shape a process engine is built for, so I put it in
> one.

### 0:45 – 1:30 · The process

Open `Release ritual` under **Processes** and show the diagram.

> Three service tasks, one user task, two gateways. The service tasks are **external tasks**: the
> engine does not run anything itself, it publishes work on a topic and a worker on my machine
> polls for it. That is why it is safe to let a process engine drive a developer machine.
>
> The middle box is a **user task**. The process stops there and waits for a person. It waits
> across a restart, because the state is in the database, not in a script.

### 1:30 – 2:45 · Start a dry run from Claude Code

In Claude Code:

```
/devflows:release 0.2.0
```

Claude checks the engine, lists the gates and starts a run with `dry_run=true`.

Point at the worker terminal while it works.

> There it is picking up the gates topic. It is running this repository's real test suite and its
> real linter, from `devflows.yaml`. The engine is just watching.

Switch to the process view and refresh.

> And the token has moved to the approval task. The gate report is already a process variable, so
> it is in the history for good.

### 2:45 – 4:00 · Approve as a human

Switch to **Tasks**, filter **My Group Tasks**.

> Here is the same task from the other side. It is assigned to the `camunda-admin` group, not to a
> person, so anyone in that group can pick it up.

Claim it. Show the form and the gate report. Tick **Approve this release**, add a comment, submit.

> That is the point of the whole project. Claude can start the release, watch it and report on it,
> but it cannot skip this, because this is a step in the process, not a rule in a prompt. And
> whoever approved it is in the audit trail.

Point back at the worker terminal as the tag and publish steps run.

### 4:00 – 5:00 · The result

Show the completed instance under **Processes**, in the history view.

> Completed. Every variable is here: which gates ran, what they printed, who approved and what they
> said, the tag, the release URL.

Then show the real thing:

> And this one is not a demo. Version 0.1.0 of this project was released by this process, running
> on this repository. The tag and the GitHub Release were created by the `tag` and `publish` steps.

Open <https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0>.

### The v0.1.0 release was cut by this process

For the record, so the claim can be checked rather than taken on trust:

| | |
| --- | --- |
| Process instance | `0e656a8f-9e47-11f1-be39-22fc550e6cab` |
| Started | 2026-08-22, `dry_run` false, after a dry run of the same version |
| Approved by | `demo`, in the web UI, comment "Good release" |
| Tag | `v0.1.0`, created by the `devflows.tag` step |
| Release | <https://github.com/0langa/cibseven-devflows/releases/tag/v0.1.0>, created by `devflows.publish` |

The instance is in the engine history as long as its 30-day `historyTimeToLive` allows. If it has
expired by the time you read this, the numbers above are what it recorded.

## Talking points

**CIB seven is a Camunda 7 fork.** It is a maintained open-source continuation of Camunda 7: same
engine, same `/engine-rest` API, same web apps. Everything in this
repository is standard Camunda 7 BPMN with the `camunda` extension namespace, and it opens
unchanged in Camunda Modeler 5.x as a Camunda 7 diagram. Nothing here is a special case.

**The external task pattern.** The engine holds state and publishes work on topics. Workers call
`fetchAndLock`, do the work wherever they are, and call `complete` or `failure`. The engine never
needs credentials for my machine, my machine never needs to be reachable from the engine, and a
worker crash becomes a visible incident instead of a lost step. This project uses plain HTTP with
`httpx` rather than a client library, so the pattern is visible in about eighty lines of code.

**Human in the loop.** The approval is a real BPMN user task with a generated form. It is durable,
it is auditable, and it can be answered from two places: the Tasklist web UI, or the `approve_gate`
MCP tool. Same task, same variables, either way.

**How this relates to CIB seven 2.2.** That release ships an AI agent connector and MCP support:
the container even has `AI_AGENT_ENABLED=true` by default, so a process can call out to an AI
agent as a step. This project comes at the same problem from the opposite side: instead of the
process calling an AI, the AI drives the process, and the process is what keeps it honest. The two
directions compose — a future flow could have an agent draft release notes as a step inside the
same process that stops to ask me before publishing them.

**Why not a shell script.** A script has no memory, no history and nowhere to wait. Everything this
project gets for free — durable waiting, an audit trail, a web UI for the human step, retries and
incidents when a step fails — comes from putting the process in an engine instead of in a file.

## If something goes wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| A run starts but nothing happens | The worker is not running | `uv run devflows-worker` in a second terminal |
| `start_release` fails with a connection error | The engine is not up yet | `docker compose -f engine/docker-compose.yml up -d`, then wait for `/engine-rest/version` |
| `start_release` fails saying the process is unknown | The process is not deployed | Call the `deploy_process` MCP tool, or the curl command above |
| The task does not appear | Wrong filter | Select **My Group Tasks**, not **My Tasks**; the task belongs to the group until you claim it |
| The engine crashes on start with `AccessDeniedException` | The `cibseven-init` service did not run | Use `docker compose up -d`, not `docker run`; see [engine/README.md](../engine/README.md) |

## Reset between demos

Completed instances stay in the history, which is usually what you want. To start from a clean
engine:

```bash
docker compose -f engine/docker-compose.yml down -v
```

```bash
docker compose -f engine/docker-compose.yml up -d
```

Then deploy the process again. A dry run never creates a tag, so nothing has to be cleaned up in
the repository itself.
