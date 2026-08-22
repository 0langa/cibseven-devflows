"""The three packages must be importable and agree on the version."""

import devflows_core
import devflows_mcp
import devflows_worker

EXPECTED_VERSION = "0.1.0"


def test_all_packages_share_one_version():
    assert devflows_core.__version__ == EXPECTED_VERSION
    assert devflows_worker.__version__ == EXPECTED_VERSION
    assert devflows_mcp.__version__ == EXPECTED_VERSION
