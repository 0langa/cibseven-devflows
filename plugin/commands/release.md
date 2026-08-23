---
description: Cut a release of this repository through the cibseven-devflows BPMN process
argument-hint: <version> [--real]
---

Release version `$1` of the repository in the current working directory through the
cibseven-devflows release process.

Follow the `release-with-devflows` skill exactly:

1. Call `doctor` with the repository path. Fix whatever is not `ok` - deploy the process or the
   decision with `deploy_process` if either is missing - before going on.
2. Show the gates with `list_gates`.
3. Start a dry run with `start_release(repo_path, "$1", dry_run=true)`.
4. Poll `get_run` and show me the gate report.
5. Then handle whichever of the two outcomes happened:
   - **No task appeared and the run has finished.** The DMN policy auto-approved it. Do not wait
     for an approval that will never come: report `policy.policy_reason` so I know why nobody was
     asked.
   - **A task is open.** Show me the gate report, the drafted `release_notes` and `notes_source`,
     then stop and ask me before calling `approve_gate`. Do not approve on your own judgement. If
     I want different notes, tell me to edit them in the web UI form - `approve_gate` cannot send
     them.
6. Report `tag_name`, `release_url` and `state` when the run ends. If the run is stuck, show the
   `incidents` from `get_run` and name the likely cause before suggesting `retry_run`.

Only start a real run (`dry_run=false`) if I passed `--real` and the dry run finished cleanly.
If I did not pass `--real`, finish after the dry run and tell me what the real run would do.
