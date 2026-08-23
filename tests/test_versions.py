"""How the candidate version is compared against the previous release."""

import pytest

from devflows_core.versions import classify_release


@pytest.mark.parametrize(
    ("previous", "candidate", "expected"),
    [
        (None, "1.0.0", "major"),
        ("", "1.0.0", "major"),
        ("   ", "1.0.0", "major"),
        ("1.2.3", "2.0.0", "major"),
        ("1.2.3", "1.3.0", "minor"),
        ("1.2.3", "1.2.4", "patch"),
        ("v1.2.3", "1.2.4", "patch"),
        ("1.2.3", "v2.0.0", "major"),
        ("v1.2.3", "v1.3.0", "minor"),
        ("1.2.3", "1.2.3", "patch"),
        ("v1.2.3", "1.2.3", "patch"),
    ],
)
def test_classify_release(previous, candidate, expected):
    assert classify_release(previous, candidate) == expected


def test_a_pre_release_suffix_is_ignored():
    assert classify_release("1.2.3", "1.3.0-rc1") == "minor"
    assert classify_release("1.2.3-rc1", "1.2.4") == "patch"


def test_a_build_suffix_is_ignored():
    assert classify_release("v1.2.3+build.7", "v2.0.0+build.8") == "major"


def test_garbage_is_unknown():
    assert classify_release("1.2.3", "not-a-version") == "unknown"
    assert classify_release("release-candidate", "1.2.3") == "unknown"
    assert classify_release("1.2", "1.3") == "unknown"
    assert classify_release("1.2.3", "1.2.3.4") == "unknown"


def test_a_first_release_wins_over_an_unparseable_candidate():
    # No previous tag means a human decides anyway, so there is nothing to compare.
    assert classify_release(None, "nightly") == "major"
