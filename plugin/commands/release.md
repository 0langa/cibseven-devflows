---
description: Cut a release of this repository through the cibseven-devflows BPMN process
argument-hint: <version> [--real]
---

Release version `$1` of the repository in the current working directory through the
cibseven-devflows release process.

Follow the `release-with-devflows` skill exactly:

1. Check `engine_status`, and `list_processes` for `devflows-release`. Deploy it if it is missing.
2. Show the gates with `list_gates`.
3. Start a dry run with `start_release(repo_path, "$1", dry_run=true)`.
4. Poll `get_run` and show the gate report.
5. Stop and ask me before calling `approve_gate`.
6. Report `tag_name` and `release_url` when the run ends.

Only start a real run (`dry_run=false`) if I passed `--real` and the dry run finished cleanly.
If I did not pass `--real`, finish after the dry run and tell me what the real run would do.
