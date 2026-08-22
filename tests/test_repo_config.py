"""This repository must be releasable by its own process."""

from pathlib import Path

import yaml

from devflows_core.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_this_repository_has_a_valid_devflows_config():
    config = load_config(REPO_ROOT)
    assert [gate.name for gate in config.gates] == ["tests", "lint"]
    assert config.tag.format == "v{version}"
    assert "gh release create" in config.publish.run


def test_the_compose_file_pins_the_image_and_keeps_the_database():
    compose = yaml.safe_load((REPO_ROOT / "engine" / "docker-compose.yml").read_text("utf-8"))
    service = compose["services"]["cibseven"]
    assert service["image"].startswith("cibseven/cibseven:")
    assert "8080:8080" in service["ports"]
    assert any("/camunda/camunda-h2-dbs" in volume for volume in service["volumes"])
    assert "cibseven-h2" in compose["volumes"]


def test_the_compose_file_hands_the_volume_to_the_engine_user():
    # The image has no /camunda/camunda-h2-dbs, so Docker creates the mount
    # point as root and the engine, running as uid 1000, cannot write there.
    # A one-shot init service fixes that before the engine starts.
    compose = yaml.safe_load((REPO_ROOT / "engine" / "docker-compose.yml").read_text("utf-8"))
    init = compose["services"]["cibseven-init"]
    assert init["user"] == "root"
    assert "1000:1000" in " ".join(init["entrypoint"])
    depends = compose["services"]["cibseven"]["depends_on"]["cibseven-init"]
    assert depends["condition"] == "service_completed_successfully"
