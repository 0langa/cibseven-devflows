"""Skip every test in this package unless a real engine answers."""

import pytest

from devflows_core.engine import EngineClient


@pytest.fixture(scope="session")
def live_engine():
    client = EngineClient(timeout=5.0)
    status = client.engine_status()
    if not status["reachable"]:
        client.close()
        pytest.skip(f"No engine at {status['url']}: {status['error']}")
    yield client
    client.close()
