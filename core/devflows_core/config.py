"""Read a repository's devflows.yaml into typed configuration objects.

The file describes what each step of the release process runs. Keeping the
parsing here means the worker never has to guess what a half-written config
means: either it produces a DevflowsConfig or it raises ConfigError with a
message a human can act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_FILENAME = "devflows.yaml"
DEFAULT_TAG_FORMAT = "v{version}"


class ConfigError(Exception):
    """The configuration file is missing, unreadable or incomplete."""


@dataclass(frozen=True)
class Gate:
    """One quality gate: a name for humans and a shell command to run."""

    name: str
    run: str


@dataclass(frozen=True)
class TagConfig:
    """How to build the tag name from the version."""

    format: str = DEFAULT_TAG_FORMAT


@dataclass(frozen=True)
class PublishConfig:
    """The shell command that publishes the release."""

    run: str


@dataclass(frozen=True)
class DevflowsConfig:
    """Everything the release process needs to know about one repository."""

    gates: tuple[Gate, ...]
    tag: TagConfig
    publish: PublishConfig


def parse_config(text: str, source: str = "<string>") -> DevflowsConfig:
    """Parse the text of a devflows.yaml file."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{source} is not valid YAML: {error}") from error

    if document is None or not isinstance(document, dict):
        raise ConfigError(f"{source} must contain a mapping at the top level")

    return DevflowsConfig(
        gates=_parse_gates(document.get("gates"), source),
        tag=_parse_tag(document.get("tag"), source),
        publish=_parse_publish(document.get("publish"), source),
    )


def load_config(repo_path: str | Path) -> DevflowsConfig:
    """Read devflows.yaml from a repository directory."""
    repo = Path(repo_path)
    if not repo.is_dir():
        raise ConfigError(f"Repository path does not exist: {repo}")

    config_file = repo / CONFIG_FILENAME
    if not config_file.is_file():
        raise ConfigError(f"No {CONFIG_FILENAME} in {repo}")

    return parse_config(config_file.read_text(encoding="utf-8"), source=str(config_file))


def _parse_gates(raw: object, source: str) -> tuple[Gate, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{source} must define at least one gate under 'gates'")

    gates = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: gate {index} must be a mapping")
        name = entry.get("name")
        run = entry.get("run")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{source}: gate {index} needs a non-empty 'name'")
        if not isinstance(run, str) or not run.strip():
            raise ConfigError(f"{source}: gate '{name}' needs a non-empty 'run'")
        gates.append(Gate(name=name, run=run))
    return tuple(gates)


def _parse_tag(raw: object, source: str) -> TagConfig:
    if raw is None:
        return TagConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: 'tag' must be a mapping")
    tag_format = raw.get("format", DEFAULT_TAG_FORMAT)
    if not isinstance(tag_format, str) or not tag_format.strip():
        raise ConfigError(f"{source}: 'tag.format' must be a non-empty string")
    return TagConfig(format=tag_format)


def _parse_publish(raw: object, source: str) -> PublishConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source} must define a 'publish' mapping")
    run = raw.get("run")
    if not isinstance(run, str) or not run.strip():
        raise ConfigError(f"{source}: 'publish.run' must be a non-empty string")
    return PublishConfig(run=run)
