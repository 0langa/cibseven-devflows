"""Find the BPMN file that ships with this project."""

from __future__ import annotations

import os
from pathlib import Path

BPMN_RELATIVE_PATH = Path("processes") / "release.bpmn"


class BpmnNotFound(FileNotFoundError):
    """The release process file could not be located."""


def default_bpmn_path() -> Path:
    """Locate processes/release.bpmn.

    DEVFLOWS_BPMN_PATH wins if it is set. Otherwise walk up from this file and
    from the current directory, which covers both a checkout and an editable
    install.
    """
    override = os.environ.get("DEVFLOWS_BPMN_PATH")
    if override:
        path = Path(override)
        if not path.is_file():
            raise BpmnNotFound(f"DEVFLOWS_BPMN_PATH points at a missing file: {path}")
        return path

    for start in (Path(__file__).resolve(), Path.cwd().resolve() / "_"):
        for parent in start.parents:
            candidate = parent / BPMN_RELATIVE_PATH
            if candidate.is_file():
                return candidate

    raise BpmnNotFound(
        "Could not find processes/release.bpmn. Set DEVFLOWS_BPMN_PATH to its location."
    )
