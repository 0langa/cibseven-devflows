# Five-minute demo

A cold start to a finished release in under ten minutes, and a five-minute script to run in front
of someone.

## Before the demo

Run these in order. The whole block takes about three minutes, most of it waiting for the engine.

**1. Start the engine.**

```bash
docker compose -f engine/docker-compose.yml up -d
```

**2. Install the project.**

```bash
uv sync
```

**3. Deploy the process and the decision table.**

```bash
curl -s -X POST http://localhost:8080/engine-rest/deployment/create -F "deployment-name=cibseven-devflows" -F "release.bpmn=@processes/release.bpmn" -F "release-policy.dmn=@processes/release-policy.dmn"
```

**4. Check everything in one command.**

```bash
uv run devflows-doctor
```

Every line must say `ok`. If one does not, it tells you what to do about it. This is also a good
opening move in front of an audience: it shows the whole setup in seven lines.

**5. Start the worker in its own terminal and leave it visible.**

```bash
uv run devflows-worker
```

It prints `Waiting for work on: devflows.gates, devflows.notes, devflows.tag, devflows.publish,
devflows.untag`. Put this terminal where the audience can see it; it is the part that shows the
work actually happening.

**6. Open two browser tabs**, both logged in at <http://localhost:8080/webapp/> as `demo` / `demo`:

- **Processes**: <http://localhost:8080/webapp/#/seven/auth/processes/list> , on `Release ritual`
- **Tasks**: <http://localhost:8080/webapp/#/seven/auth/tasks> , filter **My Group Tasks**

Use this front-end, not the older webapps under `/camunda/app/`. CIB seven 2.2 still serves those,
but every page there carries a red banner saying the interface is deprecated and no longer
supported.

**7. Have Claude Code open** in this repository, with the plugin loaded.

## The script

### 0:00 – 0:45 · What this is

> CIB seven is an open-source fork of the Camunda 7 BPM engine, maintained by CIB. This project
> takes a thing I do by hand every week, cutting a release, and runs it as a BPMN process on it.
>
> A release is a process: run the tests, look at them, decide, tag, publish. It has a human
> decision in the middle. That is exactly the shape a process engine is built for, so I put it in
> one.

### 0:45 – 1:45 · The process

Open `Release ritual` under **Processes** and show the diagram.

> Three kinds of box. The ones with a gear are **external tasks**: the engine does not run anything
> itself, it publishes work on a topic and a worker on my machine polls for it. That is why it is
> safe to let a process engine drive a developer machine.
>
> The one in the middle is a **user task**. The process stops there and waits for a person. It waits
> across a restart, because the state is in the database, not in a script. And it has a timer on it,
> so a release nobody answers rejects itself instead of hanging around forever.
>
> The one before it is a **business rule task**. It calls a DMN decision table that decides whether
> a human is needed at all.

Then point at the bottom right.

> And this is the part I like most. If publishing fails after the tag was created, that error
> boundary event throws **compensation**, which runs the undo handler and deletes the tag. A release
> that goes wrong does not leave half of itself behind.

### 1:45 – 2:30 · The policy is data, not code

Open `processes/release-policy.dmn` in Camunda Modeler, or just show the table in the README.

> A patch release with green gates ships without asking anyone. Anything bigger asks me. That rule
> is a DMN table, not an `if` in my Python. If the team decides tomorrow that minor releases can go
> out automatically too, someone edits one cell and redeploys. No code review, no deployment of my
> worker.

### 2:30 – 3:30 · Start a release from Claude Code

In Claude Code:

```
/devflows:release 0.3.0
```

Claude runs `doctor`, lists the gates, and starts a run with `dry_run=true`.

Point at the worker terminal while it works.

> There it is running this repository's real test suite and its real linter, from `devflows.yaml`.
> Then it drafts the release notes: it collects the commits since the last tag and asks the local
> Claude CLI to write them. The engine is just watching.

Switch to the process view and refresh.

> The token stopped at the approval, because 0.3.0 is a minor release and the decision table says a
> minor release needs a person.

### 3:30 – 4:30 · Approve as a human

Switch to **Tasks**, **My Group Tasks**, and claim the task.

> Here is the same task from the other side. It is assigned to the `camunda-admin` group, not to a
> person, so anyone in that group can pick it up.
>
> The form has the gate results, and the release notes the AI drafted. I can edit them right here,
> and what I approve is what gets published. That is the shape I want for an AI in a workflow: it
> does the tedious part, a person owns the result, and the process is what enforces that. Claude can
> start this release and watch it, but it cannot approve it, because approving is a step in the
> process rather than a rule in a prompt.

Tick **Approve this release**, submit, and point back at the worker terminal as the tag and publish
steps run.

### 4:30 – 5:00 · The result

Show the completed instance under **Processes**, in the history view.

> Completed. Every variable is here: which gates ran and what they printed, what the policy decided
> and why, who approved and what they changed, the tag, the release URL.

Then:

> And this is not a demo repository. Version 0.1.0 of this project was released by this exact
> process running on itself, and so was 0.2.0.

Open <https://github.com/0langa/cibseven-devflows/releases>.

## Optional: show the timer or the compensation

Both are quick and both land well if there is time or a question.

**The timer.** Start a run with a two-minute deadline and simply do not answer it:

```bash
uv run pytest tests/integration/test_live_release.py -k timer -q
```

Or start one by hand with `approval_timeout` set to `PT2M`, then watch the instance end by itself.

**Compensation.** The integration suite proves it against the real engine, on a throwaway
repository: the tag is created, the push fails because there is no remote, and the tag is gone
afterwards.

```bash
uv run pytest tests/integration/test_live_release.py -k compensat -q
```

## Talking points

**CIB seven is a Camunda 7 fork.** It is a maintained open-source continuation of Camunda 7: same
engine, same `/engine-rest` API, same web apps. Everything in this repository is standard Camunda 7
BPMN and DMN with the `camunda` extension namespace, and it opens unchanged in Camunda Modeler 5.x
as Camunda 7 files. Nothing here is a special case.

**The external task pattern.** The engine holds state and publishes work on topics. Workers call
`fetchAndLock`, do the work wherever they are, and call `complete`, `failure` or `bpmnError`. The
engine never needs credentials for my machine, my machine never needs to be reachable from the
engine, and a worker crash becomes a visible incident instead of a lost step. This project uses
plain HTTP with `httpx` rather than a client library, so the pattern is visible in about eighty
lines of code.

**Failure versus error.** These are not the same thing and the engine treats them differently. A
network blip is a *failure*: the worker reports it with retries left and a backoff, and only an
exhausted retry count raises an incident. A publish that was refused is a *BPMN error*: it will not
work next time, so the diagram catches it and compensates. Getting that distinction right is most of
what makes a workflow survivable in production.

**Human in the loop.** The approval is a real BPMN user task with a generated form. It is durable,
it is auditable, and it can be answered from two places: the web UI, or the `approve_gate` MCP tool.
Same task, same variables, either way.

**How this relates to CIB seven 2.2.** That release ships an AI agent connector and MCP support:
the container even has `AI_AGENT_ENABLED=true` by default, so a process can call out to an AI agent
as a step. This project does both halves. The AI drives the process from outside over MCP, and the
process calls an AI from inside for the release notes — with a human between that draft and anything
public.

**Why not a shell script.** A script has no memory, no history and nowhere to wait. Durable waiting,
an audit trail, a web UI for the human step, a decision table anyone can edit, retries, incidents,
and compensation that undoes work: all of that comes from putting the process in an engine instead
of in a file.

## If something goes wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| Anything at all | Unknown | `uv run devflows-doctor` first; it names the problem |
| A run starts but nothing happens | The worker is not running | `uv run devflows-worker` in a second terminal |
| The run finished without asking me | The policy auto-approved it | Expected for a patch release; `policy_reason` says so |
| The task never appeared and the run ended | The approval timer fired | Start again with a longer `approval_timeout` |
| A run is stuck | An incident | `get_run` reports it; fix the cause, then `retry_run` |
| The task does not appear | Wrong filter | Select **My Group Tasks**, not **My Tasks** |
| The engine crashes on start with `AccessDeniedException` | The `cibseven-init` service did not run | Use `docker compose up -d`; see [engine/README.md](../engine/README.md) |

## Reset between demos

Completed instances stay in the history, which is usually what you want. To start from a clean
engine:

```bash
docker compose -f engine/docker-compose.yml down -v
```

```bash
docker compose -f engine/docker-compose.yml up -d
```

Then deploy the process and the decision again. A dry run never creates a tag, so nothing has to be
cleaned up in the repository itself.

## The releases this process cut

For the record, so the claim can be checked rather than taken on trust.

| Version | Process instance | Notes |
| --- | --- | --- |
| v0.1.0 | `0e656a8f-9e47-11f1-be39-22fc550e6cab` | Approved by `demo` in the web UI, comment "Good release" |
| v0.2.0 | `665766a1-9f06-11f1-be39-22fc550e6cab` | Notes drafted by `claude`; the policy required approval because 0.2.0 is a minor release |

The v0.2.0 body had to be corrected afterwards: the approval form flattened the multi-line notes
into one line, and the model added prose around them. Both are fixed and covered by tests, but the
release itself was already public by then.

Each instance stays in the engine history for as long as its 30-day `historyTimeToLive` allows.
