"""Adversarial report checks independent of public mutant names."""
import copy

import pytest

from lab9 import gate

pytestmark = pytest.mark.student


@pytest.fixture
def reports():
    spec = {"eval_set_version": "v2", "seeds": [17, 29],
            "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                         "threshold": {"min": .8, "no_significant_drop": True}}],
            "slices": [{"name": "money", "metric": "pass_rate", "min": .9,
                        "blocking": True, "no_significant_drop": True}]}
    base = {"manifest": {"eval_set_sha": "fixture", "items": 3, "seeds": [17, 29]},
            "metrics": {"pass_rate": 1.0}, "evaluator_failures": [],
            "rows": [{"item_id": f"ITEM-{i}", "seed": seed, "pass_rate": True,
                      "slices": ["money"] if i == 0 else []}
                     for i in range(3) for seed in (17, 29)]}
    return copy.deepcopy(base), base, spec


@pytest.mark.parametrize("attack", ["duplicate", "seed", "item", "slice", "null", "nan_row",
                                   "nan_aggregate", "inf_extra", "evaluator_error", "aggregate"])
def test_advanced_report_evidence_cannot_be_hidden(reports, attack):
    pr, base, spec = reports
    if attack == "duplicate":
        pr["rows"][-1] = copy.deepcopy(pr["rows"][0])
    elif attack == "seed":
        pr["manifest"]["seeds"][0] = 999
        for row in pr["rows"]:
            if row["seed"] == 17:
                row["seed"] = 999
    elif attack == "item":
        for row in pr["rows"]:
            if row["item_id"] == "ITEM-2":
                row["item_id"] = "other"
    elif attack == "slice":
        for row in pr["rows"]:
            row["slices"] = []
    elif attack == "null":
        pr["rows"][0]["pass_rate"] = None
    elif attack == "nan_row":
        pr["rows"][0]["pass_rate"] = float("nan")
    elif attack == "nan_aggregate":
        pr["metrics"]["pass_rate"] = float("nan")
    elif attack == "inf_extra":
        pr["metrics"]["ungraded"] = float("inf")
    elif attack == "evaluator_error":
        pr["evaluator_failures"] = ["grader crashed despite green rows"]
    elif attack == "aggregate":
        pr["rows"][0]["pass_rate"] = False
    blocked, lines = gate.check(pr, base, spec)
    assert blocked == ["integrity"]
    assert any("INTEGRITY" in line for line in lines)


@pytest.mark.parametrize("attack", ["floor", "drop_ci", "drop_metric", "unblock", "drop_slice",
                                   "slice_floor", "slice_ci", "slice_unblock"])
def test_advanced_ratchet_preserves_all_existing_constraints(reports, attack):
    pr, base, original = reports
    spec = copy.deepcopy(original)
    if attack == "floor":
        spec["metrics"][0]["threshold"]["min"] = .1
    elif attack == "drop_ci":
        del spec["metrics"][0]["threshold"]["no_significant_drop"]
    elif attack == "drop_metric":
        spec["metrics"] = []
    elif attack == "unblock":
        spec["metrics"][0]["blocking"] = False
    elif attack == "drop_slice":
        spec["slices"] = []
    elif attack == "slice_floor":
        spec["slices"][0]["min"] = .1
    elif attack == "slice_ci":
        del spec["slices"][0]["no_significant_drop"]
    elif attack == "slice_unblock":
        spec["slices"][0]["blocking"] = False
    assert gate.integrity_check(pr, base, spec, original)


def test_advanced_pairing_is_independent_of_row_order(reports):
    pr, base, spec = reports
    pr["rows"].reverse()
    assert gate.check(pr, base, spec, spec)[0] == []


def test_advanced_empty_slice_is_not_a_green_gate(reports):
    pr, base, spec = reports
    spec["slices"][0]["name"] = "missing"
    assert gate.slice_check(pr, base, spec)[0] == ["slice:missing/pass_rate"]
