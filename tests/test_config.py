"""Parsing devflows.yaml into typed configuration objects."""

import pytest

from devflows_core.config import (
    ConfigError,
    DevflowsConfig,
    Gate,
    load_config,
    parse_config,
)

VALID = """
gates:
  - name: tests
    run: uv run pytest -q
  - name: lint
    run: uv run ruff check .

tag:
  format: "v{version}"

publish:
  run: gh release create v{version} --generate-notes
"""


def test_parses_a_valid_file():
    config = parse_config(VALID)
    assert isinstance(config, DevflowsConfig)
    assert config.gates == (
        Gate(name="tests", run="uv run pytest -q"),
        Gate(name="lint", run="uv run ruff check ."),
    )
    assert config.tag.format == "v{version}"
    assert config.publish.run == "gh release create v{version} --generate-notes"


def test_tag_format_defaults_to_v_prefix():
    config = parse_config("gates:\n  - name: t\n    run: echo t\npublish:\n  run: echo hi\n")
    assert config.tag.format == "v{version}"


def test_unknown_top_level_keys_are_ignored():
    config = parse_config(VALID + "\nfuture_step:\n  run: echo hi\n")
    assert len(config.gates) == 2


def test_empty_gate_list_is_an_error():
    with pytest.raises(ConfigError, match="at least one gate"):
        parse_config("gates: []\npublish:\n  run: echo hi\n")


def test_missing_gates_key_is_an_error():
    with pytest.raises(ConfigError, match="at least one gate"):
        parse_config("publish:\n  run: echo hi\n")


def test_gate_without_run_is_an_error():
    with pytest.raises(ConfigError, match="run"):
        parse_config("gates:\n  - name: tests\npublish:\n  run: echo hi\n")


def test_missing_publish_is_an_error():
    with pytest.raises(ConfigError, match="publish"):
        parse_config("gates:\n  - name: t\n    run: echo t\n")


def test_malformed_yaml_is_an_error():
    with pytest.raises(ConfigError, match="not valid YAML"):
        parse_config("gates: [unclosed\n")


def test_non_mapping_document_is_an_error():
    with pytest.raises(ConfigError, match="mapping"):
        parse_config("- just\n- a\n- list\n")


def test_error_message_names_the_source():
    with pytest.raises(ConfigError, match="my-repo/devflows.yaml"):
        parse_config("gates: []\npublish:\n  run: x\n", source="my-repo/devflows.yaml")


def test_load_config_reads_the_file_from_a_repository(tmp_path):
    (tmp_path / "devflows.yaml").write_text(VALID, encoding="utf-8")
    config = load_config(tmp_path)
    assert config.gates[0].name == "tests"


def test_load_config_reports_a_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="No devflows.yaml"):
        load_config(tmp_path)


def test_load_config_reports_a_missing_repository(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "nope")
