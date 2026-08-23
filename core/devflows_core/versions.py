"""Decide how big a release is by comparing it with the previous one.

The answer feeds the release policy decision table, which is why it is a
string and not a boolean: the table, not this module, owns the rule about who
has to approve what.
"""

from __future__ import annotations

import re

MAJOR = "major"
MINOR = "minor"
PATCH = "patch"
UNKNOWN = "unknown"

# A leading "v" is common in tags, and a pre-release or build suffix says
# nothing about the size of the change, so both are accepted and dropped.
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def classify_release(previous: str | None, candidate: str) -> str:
    """Return "major", "minor", "patch" or "unknown" for a candidate version."""
    if previous is None or not previous.strip():
        # A first release has nothing to compare against and always needs a human.
        return MAJOR

    previous_parts = _parse(previous)
    candidate_parts = _parse(candidate)
    if previous_parts is None or candidate_parts is None:
        return UNKNOWN

    if previous_parts[0] != candidate_parts[0]:
        return MAJOR
    if previous_parts[1] != candidate_parts[1]:
        return MINOR
    return PATCH


def _parse(version: str) -> tuple[int, int, int] | None:
    """Split a version into major, minor and patch, or None if it is not one."""
    match = _VERSION_PATTERN.match(version.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))
