"""The DMN table is a deliverable. Check its contract, not its layout."""

from pathlib import Path
from xml.etree import ElementTree

import pytest

from devflows_core.paths import default_bpmn_path

DMN_NS = "https://www.omg.org/spec/DMN/20191111/MODEL/"
DMNDI_NS = "https://www.omg.org/spec/DMN/20191111/DMNDI/"
NS = {"dmn": DMN_NS, "dmndi": DMNDI_NS}


def default_dmn_path() -> Path:
    """The decision table sits next to the BPMN file that ships with the project."""
    return default_bpmn_path().parent / "release-policy.dmn"


@pytest.fixture(scope="module")
def decision():
    tree = ElementTree.parse(default_dmn_path())
    return tree.getroot().find("dmn:decision", NS)


@pytest.fixture(scope="module")
def table(decision):
    return decision.find("dmn:decisionTable", NS)


@pytest.fixture(scope="module")
def rules(table):
    return table.findall("dmn:rule", NS)


def entries(rule, tag):
    """The text of every inputEntry or outputEntry of one rule, in order."""
    cells = rule.findall(f"dmn:{tag}", NS)
    return [cell.findtext("dmn:text", default="", namespaces=NS).strip() for cell in cells]


def test_the_dmn_file_can_be_found():
    assert default_dmn_path().is_file()


def test_the_decision_key_is_release_policy(decision):
    assert decision.get("id") == "release-policy"
    assert decision.get("name")


def test_the_hit_policy_is_first(table):
    assert table.get("hitPolicy") == "FIRST"


def test_the_inputs_are_release_kind_and_gates_passed(table):
    expressions = table.findall("dmn:input/dmn:inputExpression", NS)
    names = [expression.findtext("dmn:text", default="", namespaces=NS).strip()
             for expression in expressions]
    assert names == ["release_kind", "gates_passed"]
    assert [expression.get("typeRef") for expression in expressions] == ["string", "boolean"]


def test_the_outputs_are_approval_required_and_policy_reason(table):
    outputs = table.findall("dmn:output", NS)
    assert [output.get("name") for output in outputs] == ["approval_required", "policy_reason"]
    assert [output.get("typeRef") for output in outputs] == ["boolean", "string"]


def test_there_are_three_rules(rules):
    assert len(rules) == 3


def test_a_green_patch_release_needs_no_approval(rules):
    assert entries(rules[1], "inputEntry") == ['"patch"', "true"]
    assert entries(rules[1], "outputEntry")[0] == "false"


def test_the_last_rule_catches_everything_and_asks_a_human(rules):
    assert entries(rules[-1], "inputEntry") == ["", ""]
    assert entries(rules[-1], "outputEntry")[0] == "true"


def test_the_diagram_has_a_shape_so_the_modeler_can_render_it():
    root = ElementTree.parse(default_dmn_path()).getroot()
    assert root.find("dmndi:DMNDI", NS) is not None
    assert len(root.findall(".//dmndi:DMNShape", NS)) >= 1
