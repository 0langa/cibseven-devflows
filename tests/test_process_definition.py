"""The BPMN file is a deliverable. Check its contract, not its layout."""

from xml.etree import ElementTree

import pytest

from devflows_core.paths import BpmnNotFound, default_bpmn_path

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn"
DI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
NS = {"bpmn": BPMN_NS, "camunda": CAMUNDA_NS, "bpmndi": DI_NS}


@pytest.fixture(scope="module")
def process():
    tree = ElementTree.parse(default_bpmn_path())
    return tree.getroot().find("bpmn:process", NS)


def test_the_bpmn_file_can_be_found():
    assert default_bpmn_path().is_file()


def test_the_process_key_is_devflows_release(process):
    assert process.get("id") == "devflows-release"
    assert process.get("isExecutable") == "true"


def test_history_time_to_live_is_set(process):
    assert process.get(f"{{{CAMUNDA_NS}}}historyTimeToLive") == "P30D"


def test_the_three_external_tasks_use_the_expected_topics(process):
    topics = {
        task.get(f"{{{CAMUNDA_NS}}}topic") for task in process.findall("bpmn:serviceTask", NS)
    }
    assert topics == {"devflows.gates", "devflows.tag", "devflows.publish"}


def test_every_service_task_is_an_external_task(process):
    for task in process.findall("bpmn:serviceTask", NS):
        assert task.get(f"{{{CAMUNDA_NS}}}type") == "external"


def test_there_is_exactly_one_user_task_for_the_camunda_admin_group(process):
    tasks = process.findall("bpmn:userTask", NS)
    assert len(tasks) == 1
    assert tasks[0].get(f"{{{CAMUNDA_NS}}}candidateGroups") == "camunda-admin"
    assert tasks[0].get("id") == "approve_release"


def test_the_user_task_form_asks_for_approved_and_a_comment(process):
    task = process.find("bpmn:userTask", NS)
    fields = task.findall(
        f"bpmn:extensionElements/{{{CAMUNDA_NS}}}formData/{{{CAMUNDA_NS}}}formField", NS
    )
    by_id = {field.get("id"): field.get("type") for field in fields}
    assert by_id == {"approved": "boolean", "approval_comment": "string"}


def test_both_gateways_branch_on_the_expected_variables(process):
    expressions = {
        flow.findtext("bpmn:conditionExpression", default="", namespaces=NS)
        for flow in process.findall("bpmn:sequenceFlow", NS)
        if flow.find("bpmn:conditionExpression", NS) is not None
    }
    assert "${gates_passed == true}" in expressions
    assert "${gates_passed == false}" in expressions
    assert "${approved == true}" in expressions
    assert "${approved == false}" in expressions


def test_there_are_three_end_events(process):
    ends = {event.get("id") for event in process.findall("bpmn:endEvent", NS)}
    assert ends == {"end_gates_failed", "end_rejected", "end_released"}


def test_the_diagram_has_shapes_so_the_modeler_can_render_it():
    root = ElementTree.parse(default_bpmn_path()).getroot()
    shapes = root.findall(".//bpmndi:BPMNShape", NS)
    assert len(shapes) >= 9


def test_the_environment_variable_overrides_the_search(tmp_path, monkeypatch):
    override = tmp_path / "custom.bpmn"
    override.write_text("<definitions/>", encoding="utf-8")
    monkeypatch.setenv("DEVFLOWS_BPMN_PATH", str(override))
    assert default_bpmn_path() == override


def test_a_missing_override_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLOWS_BPMN_PATH", str(tmp_path / "nope.bpmn"))
    with pytest.raises(BpmnNotFound):
        default_bpmn_path()
