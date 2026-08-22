"""Camunda REST wraps variables in {"value": ..., "type": ...}. Go both ways."""

from devflows_core.variables import from_engine, to_engine


def test_encodes_python_types_to_camunda_types():
    encoded = to_engine({"repo_path": "C:/repo", "dry_run": True, "retries": 3, "ratio": 0.5})
    assert encoded["repo_path"] == {"value": "C:/repo", "type": "String"}
    assert encoded["dry_run"] == {"value": True, "type": "Boolean"}
    assert encoded["retries"] == {"value": 3, "type": "Long"}
    assert encoded["ratio"] == {"value": 0.5, "type": "Double"}


def test_encodes_none_as_a_null_string():
    assert to_engine({"comment": None}) == {"comment": {"value": None, "type": "String"}}


def test_booleans_are_not_mistaken_for_integers():
    # bool is a subclass of int in Python; the order of the checks matters.
    assert to_engine({"flag": False})["flag"]["type"] == "Boolean"


def test_unknown_types_become_strings():
    encoded = to_engine({"path": ["a", "b"]})
    assert encoded["path"]["type"] == "String"
    assert encoded["path"]["value"] == "['a', 'b']"


def test_decodes_a_camunda_payload():
    payload = {
        "gates_passed": {"value": True, "type": "Boolean"},
        "tag_name": {"value": "v0.1.0", "type": "String"},
    }
    assert from_engine(payload) == {"gates_passed": True, "tag_name": "v0.1.0"}


def test_decoding_an_empty_payload_gives_an_empty_dict():
    assert from_engine({}) == {}


def test_decoding_tolerates_entries_that_are_not_wrapped():
    assert from_engine({"raw": "plain"}) == {"raw": "plain"}
