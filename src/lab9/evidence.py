"""Reproduce taxonomy examples and summarize generated reports without exposing raw traces."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import tempfile

from pydantic_evals.evaluators import EvaluatorContext

from lab8.console import utf8_stdio
from lab8.shapes import SHAPES
from lab9 import stats
from lab9.eval import load_world, per_item
from lab9.graders import GRADERS
from lab9.variant_agent import make_shape

EXAMPLES = {
    "FM-01": ("C-001", {"no_override", "leaky_trace"}),
    "FM-02": ("C-007", {"no_override", "ignore_denied"}),
    "FM-03": ("C-002", {"ticket_trust"}),
    "FM-04": ("C-014", {"no_override", "sum_parts"}),
    "FM-05": ("C-014", {"no_override", "pre_deducted"}),
    "FM-06": ("C-006", {"no_override", "stale_clause"}),
    "FM-07": ("C-001", {"no_override", "sibling_refund"}),
    "FM-08": ("C-008", {"no_override", "misreport"}),
    "FM-09": ("C-005", {"no_override"}),
}


def summarize_event(event):
    kind, payload = event["kind"], event.get("payload") or {}
    if kind == "debug_claim_row":
        return {"kind": kind, "payload": {"redacted": True}}
    if kind == "investigator":
        view = payload.get("lookup_order", {})
        payload = {"visible": view.get("visible"), "db_delay_days": (view.get("order") or {}).get("delay_days"),
                   "policy_count": payload.get("policy_count")}
    else:
        allowed = {"delay_days", "amount_vnd", "status", "reason", "text", "refund_count", "refunded_vnd", "ok"}
        payload = {key: value for key, value in payload.items() if key in allowed}
    return {"kind": kind, "payload": payload}


def taxonomy_examples():
    from lab9.eval import make_task
    world, claims = load_world({})
    labels = {claim["claim_id"]: claim["expected"] for claim in claims}
    examples = {}
    with tempfile.TemporaryDirectory(prefix="lab9-evidence-", ignore_cleanup_errors=True) as tmp:
        for fm, (claim, bugs) in EXAMPLES.items():
            name = "evidence_" + fm.lower().replace("-", "_")
            previous = SHAPES.get(name)
            SHAPES[name] = make_shape(name, bugs)
            try:
                trial = make_task(name, world, claims, labels, Path(tmp))({"claim_id": claim, "seed": 11})
                ctx = EvaluatorContext(name=fm, inputs={}, metadata=None, expected_output=labels[claim],
                                       output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})
                examples[fm] = {"claim_id": claim, "seed": 11, "bugs": sorted(bugs),
                    "run_id": trial["result"]["run_id"], "status": trial["result"]["status"],
                    "proposal_amount": trial["result"]["proposal_amount"], "ledger": trial["snapshot"],
                    "unexpected_rows": trial["unexpected_rows"],
                    "scores": {mid: bool(grader().evaluate(ctx).value) for mid, grader in GRADERS.items()},
                    "events": [dict(step=i, **summarize_event(e)) for i, e in enumerate(trial["events"], 1)],
                    "observation": "authorization_negative_control" if fm == "FM-09" else "injected_failure"}
            finally:
                if previous is None:
                    SHAPES.pop(name, None)
                else:
                    SHAPES[name] = previous
    return examples


def build():
    read = lambda name: json.loads(Path(f"reports/{name}.json").read_text(encoding="utf-8"))
    baseline, fixed, broken = (read(name) for name in ("baseline_v1", "eval_fixed", "eval_seeded_regression"))
    comparisons = {}
    for name, report in (("fixed", fixed), ("seeded_regression", broken)):
        comparisons[name] = {}
        for mid in ("pass_rate", "refund_amount_correct", "reply_ledger_consistent"):
            a, b = per_item(report, mid), per_item(baseline, mid)
            keys = sorted(a)
            comparisons[name][mid] = dict(zip(("delta", "low", "high"),
                stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys])))
    graded = [m for m in GRADERS if m != "pass_rate"]
    flagged = lambda row: any(row[m] is (m in {"secret_leak", "approval_bypass"}) for m in graded)
    failing = [row for row in broken["rows"] if not row["pass_rate"]]
    return {"run_id": f"A-{date.today():%Y%m%d}-{baseline['manifest']['eval_set_sha'][:4]}",
            "method": "public_replay_and_injected_fixtures_no_new_human_labels",
            "comparisons_v1": comparisons,
            "detection": {"failing_rows": len(failing), "flagged_failing_rows": sum(map(flagged, failing)),
                          "fixed_rows": len(fixed["rows"]), "false_alarms": sum(map(flagged, fixed["rows"]))},
            "taxonomy_examples": taxonomy_examples()}


def main(argv=None):
    utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/analysis.json")
    args = parser.parse_args(argv)
    report = build()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(report["run_id"], report["detection"])
    for fm, example in report["taxonomy_examples"].items():
        print(fm, example["claim_id"], example["observation"], example["scores"])
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
