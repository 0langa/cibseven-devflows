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


def test_every_service_task_is_an_external_task(process):
    for task in process.findall("bpmn:serviceTask", NS):
        assert task.get(f"{{{CAMUNDA_NS}}}type") == "external"


def test_there_is_exactly_one_user_task_for_the_camunda_admin_group(process):
    tasks = process.findall("bpmn:userTask", NS)
    assert len(tasks) == 1
    assert tasks[0].get(f"{{{CAMUNDA_NS}}}candidateGroups") == "camunda-admin"
    assert tasks[0].get("id") == "approve_release"


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


# ---- v0.2.0 additions ----------------------------------------------------


def test_the_notes_and_untag_topics_are_wired(process):
    topics = {
        task.get(f"{{{CAMUNDA_NS}}}topic") for task in process.findall("bpmn:serviceTask", NS)
    }
    assert topics == {
        "devflows.gates",
        "devflows.notes",
        "devflows.tag",
        "devflows.publish",
        "devflows.untag",
    }


def test_the_business_rule_task_calls_the_release_policy_decision(process):
    task = process.find("bpmn:businessRuleTask", NS)
    assert task.get("id") == "decide_policy"
    assert task.get(f"{{{CAMUNDA_NS}}}decisionRef") == "release-policy"
    # singleResult maps the decision output into one map, so the gateway can
    # read ${policy.approval_required}.
    assert task.get(f"{{{CAMUNDA_NS}}}mapDecisionResult") == "singleResult"
    assert task.get(f"{{{CAMUNDA_NS}}}resultVariable") == "policy"


def test_the_policy_gateway_branches_on_the_decision(process):
    expressions = {
        flow.findtext("bpmn:conditionExpression", default="", namespaces=NS)
        for flow in process.findall("bpmn:sequenceFlow", NS)
        if flow.find("bpmn:conditionExpression", NS) is not None
    }
    assert "${policy.approval_required == true}" in expressions
    assert "${policy.approval_required == false}" in expressions


def test_the_auto_approved_path_goes_straight_to_the_tag(process):
    flow = next(
        f for f in process.findall("bpmn:sequenceFlow", NS) if f.get("id") == "flow_auto_approved"
    )
    assert flow.get("sourceRef") == "policy_gateway"
    assert flow.get("targetRef") == "create_tag"


def test_the_approval_has_a_timer_whose_duration_is_a_variable(process):
    timer = next(
        event
        for event in process.findall("bpmn:boundaryEvent", NS)
        if event.get("id") == "approval_timer"
    )
    assert timer.get("attachedToRef") == "approve_release"
    # cancelActivity true: when the timer fires the approval is gone, not doubled.
    assert timer.get("cancelActivity") == "true"
    duration = timer.findtext(
        "bpmn:timerEventDefinition/bpmn:timeDuration", default="", namespaces=NS
    )
    assert duration == "${approval_timeout}"


def test_the_form_asks_for_a_decision_a_comment_and_an_optional_override(process):
    task = process.find("bpmn:userTask", NS)
    fields = task.findall(
        f"bpmn:extensionElements/{{{CAMUNDA_NS}}}formData/{{{CAMUNDA_NS}}}formField", NS
    )
    by_id = {field.get("id"): field for field in fields}
    assert set(by_id) == {"approved", "notes_override", "approval_comment"}


def test_the_tag_can_be_compensated(process):
    boundary = next(
        event
        for event in process.findall("bpmn:boundaryEvent", NS)
        if event.get("id") == "compensate_tag"
    )
    assert boundary.get("attachedToRef") == "create_tag"
    assert boundary.find("bpmn:compensateEventDefinition", NS) is not None

    handler = next(
        task for task in process.findall("bpmn:serviceTask", NS) if task.get("id") == "undo_tag"
    )
    # A compensation handler is never on the normal path.
    assert handler.get("isForCompensation") == "true"
    assert handler.find("bpmn:incoming", NS) is None
    assert handler.find("bpmn:outgoing", NS) is None

    association = process.find("bpmn:association", NS)
    assert association.get("sourceRef") == "compensate_tag"
    assert association.get("targetRef") == "undo_tag"


def test_a_failed_publish_is_caught_and_compensated(process):
    boundary = next(
        event
        for event in process.findall("bpmn:boundaryEvent", NS)
        if event.get("id") == "publish_failed"
    )
    assert boundary.get("attachedToRef") == "publish_release"
    assert boundary.find("bpmn:errorEventDefinition", NS) is not None

    throw = process.find("bpmn:intermediateThrowEvent", NS)
    assert throw.get("id") == "throw_compensation"
    assert throw.find("bpmn:compensateEventDefinition", NS) is not None


def test_the_error_code_matches_the_one_the_worker_raises():
    from devflows_worker.handlers import PUBLISH_FAILED

    root = ElementTree.parse(default_bpmn_path()).getroot()
    error = root.find("bpmn:error", NS)
    assert error.get("errorCode") == PUBLISH_FAILED


def test_every_ending_is_an_end_event(process):
    ends = {event.get("id") for event in process.findall("bpmn:endEvent", NS)}
    assert ends == {
        "end_gates_failed",
        "end_approval_expired",
        "end_rejected",
        "end_publish_failed",
        "end_released",
    }


def test_the_form_cannot_flatten_the_drafted_notes(process):
    """A generated string field is a single-line input.

    Giving it the drafted notes as its default meant submitting the form
    replaced multi-line markdown with one long line, which is what got
    published as the body of v0.2.0. The field is now an empty override.
    """
    task = process.find("bpmn:userTask", NS)
    fields = task.findall(
        f"bpmn:extensionElements/{{{CAMUNDA_NS}}}formData/{{{CAMUNDA_NS}}}formField", NS
    )
    by_id = {field.get("id"): field for field in fields}
    assert "release_notes" not in by_id
    assert by_id["notes_override"].get("defaultValue") == ""
