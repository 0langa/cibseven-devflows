# Local CIB seven engine

One container, one volume, no configuration.

## Start and stop

```bash
docker compose -f engine/docker-compose.yml up -d
```

```bash
docker compose -f engine/docker-compose.yml down
```

`down` keeps the database. To throw the history away as well, add `-v`.

## Where things are

| What | Where |
| --- | --- |
| Web apps (processes, tasks, admin) | <http://localhost:8080/webapp/> |
| REST API | <http://localhost:8080/engine-rest/> |
| Login | `demo` / `demo` |

The first start takes about 30 seconds before
`http://localhost:8080/engine-rest/engine` answers.

## Data

The H2 database file is `process-engine.mv.db` inside the container at
`/camunda/camunda-h2-dbs`. The compose file mounts the named volume `cibseven-h2` there, so
process history survives `down` and `up`.

That directory does not exist in the image; the engine creates it at startup. Docker therefore
creates the mount point for a fresh named volume as `root`, and the engine, which runs as uid
1000, cannot write its database into it. The compose file contains a one-shot `cibseven-init`
service that hands the directory over before the engine starts. It runs, prints nothing and
exits 0 on every `up`, which is expected. Without it the engine crashes on start with
`AccessDeniedException: /camunda/camunda-h2-dbs/process-engine.mv.db`.

## The engine has no authentication

The REST API on port 8080 is open to anything that can reach it. That is acceptable for a tool
that runs on your own machine and binds to localhost, and it is why this project sends no
credentials. Do not expose this port to a network you do not control.

## If `docker` is not on your PATH

A per-user Docker Desktop install on Windows does not always put the CLI on `PATH`. It lives at:

```
%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe
```

Use that full path, or add the directory to `PATH`.

Do not force-kill Docker Desktop processes on Windows. Leftover socket files can become
undeletable, and Docker will then refuse to start. Quit it through the tray icon or with
`docker desktop stop`.
