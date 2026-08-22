"""The devflows worker: ask the engine for work, do it, report back.

Run it with no arguments. It reads its settings from the environment:

    DEVFLOWS_ENGINE_URL     default http://localhost:8080/engine-rest
    DEVFLOWS_WORKER_ID      default devflows-worker-<hostname>
    DEVFLOWS_LOCK_MS        how long a fetched task stays locked
    DEVFLOWS_POLL_MS        how long one long-poll waits for work
"""

from __future__ import annotations

import logging
import os
import platform
import signal
import sys
from collections.abc import Callable
from typing import Any

from devflows_core.engine import EngineClient, EngineError
from devflows_core.variables import from_engine
from devflows_worker.handlers import (
    GATES_TOPIC,
    HANDLERS,
    PUBLISH_TOPIC,
    TAG_TOPIC,
    HandlerError,
)

DEFAULT_LOCK_DURATION_MS = 300_000
DEFAULT_ASYNC_TIMEOUT_MS = 10_000
DEFAULT_MAX_TASKS = 1

TOPIC_ORDER = (GATES_TOPIC, TAG_TOPIC, PUBLISH_TOPIC)
FETCHED_VARIABLES = ["repo_path", "version", "dry_run", "tag_name"]

log = logging.getLogger("devflows.worker")


def build_topics(lock_duration_ms: int = DEFAULT_LOCK_DURATION_MS) -> list[dict[str, Any]]:
    """The topic subscription list sent with every fetchAndLock call."""
    return [
        {
            "topicName": topic,
            "lockDuration": lock_duration_ms,
            "variables": list(FETCHED_VARIABLES),
        }
        for topic in TOPIC_ORDER
    ]


def handle_one(
    client: Any,
    worker_id: str,
    task: dict[str, Any],
    handlers: dict[str, Callable[..., dict[str, Any]]] = HANDLERS,
) -> str:
    """Run one fetched task and tell the engine how it went."""
    task_id = task["id"]
    topic = task.get("topicName", "")
    variables = from_engine(task.get("variables") or {})

    handler = handlers.get(topic)
    if handler is None:
        message = f"No handler for topic {topic}"
        log.error("%s (task %s)", message, task_id)
        client.fail_external_task(task_id, worker_id, message, "")
        return "failed"

    log.info("Handling %s (task %s)", topic, task_id)
    try:
        result = handler(variables)
    except HandlerError as error:
        log.warning("%s failed: %s", topic, error.message)
        client.fail_external_task(task_id, worker_id, error.message, error.details)
        return "failed"
    except Exception as error:  # noqa: BLE001 - the engine must learn about every failure
        log.exception("%s raised an unexpected error", topic)
        client.fail_external_task(task_id, worker_id, f"{type(error).__name__}: {error}", "")
        return "failed"

    client.complete_external_task(task_id, worker_id, result)
    log.info("Completed %s (task %s)", topic, task_id)
    return "completed"


def poll_once(
    client: Any,
    worker_id: str,
    *,
    lock_duration_ms: int = DEFAULT_LOCK_DURATION_MS,
    max_tasks: int = DEFAULT_MAX_TASKS,
    async_timeout_ms: int = DEFAULT_ASYNC_TIMEOUT_MS,
    handlers: dict[str, Callable[..., dict[str, Any]]] = HANDLERS,
) -> int:
    """One fetchAndLock round. Returns how many tasks were handled."""
    tasks = client.fetch_and_lock(
        worker_id, build_topics(lock_duration_ms), max_tasks, async_timeout_ms
    )
    for task in tasks:
        handle_one(client, worker_id, task, handlers=handlers)
    return len(tasks)


def main() -> None:
    """Poll the engine until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs every request at INFO. One line per long poll would bury the
    # lines that matter, so only its warnings are shown.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    worker_id = os.environ.get("DEVFLOWS_WORKER_ID") or f"devflows-worker-{platform.node()}"
    lock_ms = int(os.environ.get("DEVFLOWS_LOCK_MS", DEFAULT_LOCK_DURATION_MS))
    poll_ms = int(os.environ.get("DEVFLOWS_POLL_MS", DEFAULT_ASYNC_TIMEOUT_MS))

    running = True

    def stop(signum: int, frame: object) -> None:
        nonlocal running
        running = False
        log.info("Stopping.")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    with EngineClient(timeout=(poll_ms / 1000) + 30) as client:
        status = client.engine_status()
        if not status["reachable"]:
            log.error("Engine not reachable at %s: %s", status["url"], status["error"])
            sys.exit(1)
        log.info(
            "Worker %s connected to CIB seven %s at %s",
            worker_id,
            status["version"],
            status["url"],
        )
        log.info("Waiting for work on: %s", ", ".join(TOPIC_ORDER))

        while running:
            try:
                poll_once(
                    client,
                    worker_id,
                    lock_duration_ms=lock_ms,
                    async_timeout_ms=poll_ms,
                )
            except EngineError as error:
                log.error("Engine call failed: %s", error)


if __name__ == "__main__":
    main()
