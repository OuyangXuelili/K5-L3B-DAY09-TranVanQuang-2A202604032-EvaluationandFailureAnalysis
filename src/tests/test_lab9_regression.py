"""Regression cases for wrong decisions and reply/ledger disagreement."""
import itertools

import pytest
from pydantic_evals.evaluators import EvaluatorContext

from lab8.shapes import SHAPES
from lab9 import stats
from lab9.eval import load_world, make_task
from lab9.graders import DbFactKept, ProposalAmountCorrect, RefundAmountCorrect, ReplyLedgerConsistent
from lab9.variant_agent import make_shape

pytestmark = pytest.mark.student


def context(trial, label):
    return EvaluatorContext(name="regression", inputs={}, metadata=None, expected_output=label,
                            output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})


def run_case(tmp_path, monkeypatch, bugs, claim="C-002"):
    name = "regression_fixture"
    monkeypatch.setitem(SHAPES, name, make_shape(name, bugs))
    world, claims = load_world({})
    labels = {row["claim_id"]: row["expected"] for row in claims}
    trial = make_task(name, world, claims, labels, tmp_path)({"claim_id": claim, "seed": 11})
    return context(trial, labels[claim])


def test_lab9_first_wrong_decision_has_a_clean_control(tmp_path, monkeypatch):
    bad = run_case(tmp_path, monkeypatch, {"ticket_trust"})
    assert not bad.output["lab8_pass"]
    assert bad.output["events"][2]["kind"] == "model_override"
    assert bad.output["events"][2]["payload"]["delay_days"] == 5
    assert not DbFactKept().evaluate(bad).value
    assert not RefundAmountCorrect().evaluate(bad).value
    good = run_case(tmp_path, monkeypatch, {"no_override"})
    assert good.output["lab8_pass"]
    assert RefundAmountCorrect().evaluate(good).value
    assert DbFactKept().evaluate(good).value


def test_lab9_quiet_fact_override_is_caught_by_outcome(tmp_path, monkeypatch):
    bad = run_case(tmp_path, monkeypatch, {"quiet_override"})
    assert DbFactKept().evaluate(bad).value
    assert not RefundAmountCorrect().evaluate(bad).value


def test_lab9_fm08_needs_reply_metric_even_when_ledger_is_right(tmp_path, monkeypatch):
    bad = run_case(tmp_path, monkeypatch, {"no_override", "misreport"}, "C-008")
    assert bad.output["lab8_pass"]
    assert RefundAmountCorrect().evaluate(bad).value
    assert not ReplyLedgerConsistent().evaluate(bad).value
    good = run_case(tmp_path, monkeypatch, {"no_override", "paraphrase", "extra_lookup"}, "C-008")
    assert ReplyLedgerConsistent().evaluate(good).value


def test_lab9_pre_deducted_zero_still_has_an_incorrect_proposal(tmp_path, monkeypatch):
    bad = run_case(tmp_path, monkeypatch, {"no_override", "pre_deducted"}, "C-013")
    assert bad.output["snapshot"]["refund_vnd"] == 0
    assert RefundAmountCorrect().evaluate(bad).value
    assert not bad.output["lab8_pass"]
    assert not ProposalAmountCorrect().evaluate(bad).value
    good = run_case(tmp_path, monkeypatch, {"no_override"}, "C-013")
    assert good.output["lab8_pass"]
    assert ProposalAmountCorrect().evaluate(good).value


@pytest.mark.parametrize("text,passed", [
    ("Đã hoàn 20.000đ cho O-808.", True),
    ("LogiX đã hoàn phí 20,000 VND cho anh/chị.", True),
    ("Đã hoàn 20 000 đồng.", True),
    ("Hoàn 20000₫.", True),
    ("Đã hoàn 35.000đ cho O-808.", False),
    ("Hoàn -20.000đ.", False),
])
def test_lab9_reply_amount_formats(text, passed):
    trial = {"result": {}, "snapshot": {"refund_vnd": 20000},
             "events": [{"kind": "reply", "payload": {"text": text}}]}
    assert ReplyLedgerConsistent().evaluate(context(trial, {})).value is passed


def test_lab9_pass_estimators_match_exhaustive_sampling():
    for n in range(1, 7):
        for c in range(n + 1):
            outcomes = [True] * c + [False] * (n - c)
            for k in range(1, n + 1):
                draws = list(itertools.combinations(outcomes, k))
                assert stats.pass_at_k(n, c, k) == pytest.approx(sum(map(any, draws)) / len(draws))
                assert stats.pass_hat_k(n, c, k) == pytest.approx(sum(map(all, draws)) / len(draws))


@pytest.mark.parametrize("args", [(0, 0, 1), (-1, 0, 1), (5, -1, 2), (5, 6, 1),
                                  (5, 2, 0), (5, 2, 6), (5.0, 2, 1), (True, 1, 1)])
def test_lab9_pass_estimators_validate_counts(args):
    for fn in (stats.pass_at_k, stats.pass_hat_k):
        with pytest.raises(ValueError):
            fn(*args)


@pytest.mark.parametrize("a,b", [([], []), ([1], []), ([float("nan")], [1]), ([1], [float("inf")])])
def test_lab9_bootstrap_rejects_invalid_pairs(a, b):
    with pytest.raises(ValueError):
        stats.paired_bootstrap(a, b)
