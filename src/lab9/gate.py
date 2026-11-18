"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = []
    graded = [m["id"] for m in spec["metrics"] if m["id"] in GRADERS]

    def finite(value):
        return isinstance(value, (int, float)) and math.isfinite(value)

    metric_ids = [m["id"] for m in spec["metrics"]]
    if len(metric_ids) != len(set(metric_ids)):
        problems.append("duplicate metric ids in spec")
    for entry in spec["metrics"]:
        for name, value in entry.get("threshold", {}).items():
            if name in {"min", "max", "max_increase"} and not finite(value):
                problems.append(f"invalid threshold {entry['id']}/{name}")
    for entry in spec.get("slices", []):
        if any(name in entry and not finite(entry[name]) for name in ("min", "max")):
            problems.append(f"invalid slice threshold {entry['name']}")

    def inspect(report, name):
        manifest = report.get("manifest", {})
        rows, metrics = report.get("rows"), report.get("metrics")
        if not isinstance(rows, list) or not isinstance(metrics, dict):
            problems.append(f"{name}: missing rows or metrics")
            return set(), {}
        items, seeds = manifest.get("items"), manifest.get("seeds")
        if (type(items) is not int or items < 1 or not isinstance(seeds, list) or not seeds
                or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds)):
            problems.append(f"{name}: invalid items/seeds manifest")
            return set(), {}
        if len(rows) != items * len(seeds):
            problems.append(f"{name}: row count differs from items x seeds")
        if spec.get("seeds") is not None and set(seeds) != set(spec["seeds"]):
            problems.append(f"{name}: seeds differ from spec")
        keys, tags, valid_rows = [], {}, True
        for index, row in enumerate(rows):
            if (not isinstance(row, dict) or not isinstance(row.get("item_id"), str)
                    or type(row.get("seed")) is not int):
                problems.append(f"{name}: invalid identity at row {index}")
                valid_rows = False
                continue
            item = row["item_id"]
            keys.append((item, row["seed"]))
            slices = row.get("slices", [])
            if not isinstance(slices, list) or any(not isinstance(tag, str) for tag in slices):
                problems.append(f"{name}: invalid slice tags for {item}")
                slices = []
            current = frozenset(slices)
            if item in tags and tags[item] != current:
                problems.append(f"{name}: inconsistent slice tags for {item}")
            tags[item] = current
            for mid in graded:
                value = row.get(mid)
                if not finite(value) or value not in (0, 1):
                    problems.append(f"{name}: row {index} missing/invalid {mid}")
                    valid_rows = False
            if "cost" in row and (not finite(row["cost"]) or row["cost"] < 0):
                problems.append(f"{name}: row {index} invalid cost")
                valid_rows = False
            if any(isinstance(v, float) and not math.isfinite(v) for v in row.values()):
                problems.append(f"{name}: non-finite row {index}")
                valid_rows = False
        keyset = set(keys)
        if len(keys) != len(keyset):
            problems.append(f"{name}: duplicate (item_id, seed)")
        if len(tags) != items or keyset != {(item, seed) for item in tags for seed in seeds}:
            problems.append(f"{name}: incomplete item x seed grid")
        if report.get("evaluator_failures"):
            problems.append(f"{name}: evaluator_failures is non-empty")
        for mid, value in metrics.items():
            if not finite(value):
                problems.append(f"{name}: metric {mid} is missing/non-finite")
        for metric in spec["metrics"]:
            if not finite(metrics.get(metric["id"])):
                problems.append(f"{name}: missing spec metric {metric['id']}")
        if valid_rows and rows:
            k_values = set(spec.get("pass_k", []))
            for mid in metrics:
                match = re.fullmatch(r"pass_(?:at|hat)_(\d+)", mid)
                if match:
                    k_values.add(int(match.group(1)))
            expected = aggregate([{**row, "cost": row.get("cost", 0)} for row in rows],
                                 graded, k_values=sorted(k_values))
            for mid in set(metrics) & set(expected):
                if mid == "cost_per_success" and any("cost" not in row for row in rows):
                    problems.append(f"{name}: cost_per_success has missing row costs")
                elif finite(metrics[mid]) and (not finite(expected[mid])
                        or not math.isclose(metrics[mid], expected[mid], abs_tol=1e-9, rel_tol=1e-9)):
                    problems.append(f"{name}: aggregate {mid} differs from rows")
        return keyset, tags

    pr_keys, pr_tags = inspect(pr, "PR")
    base_keys, base_tags = inspect(base, "baseline")
    if pr_keys != base_keys:
        problems.append("PR and baseline have different (item_id, seed) sets")
    if pr_tags != base_tags:
        problems.append("PR slice tags differ from baseline")
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        def ratchet(old_entries, new_entries, key, slice_entry=False):
            indexed = {key(entry): entry for entry in new_entries}
            if len(indexed) != len(new_entries):
                problems.append("duplicate metric/slice in spec")
            for old in old_entries:
                label = str(key(old))
                new = indexed.get(key(old))
                if new is None:
                    problems.append(f"ratchet: removed {label}")
                    continue
                if old.get("blocking") and not new.get("blocking"):
                    problems.append(f"ratchet: disabled blocking {label}")
                if old.get("kind") != new.get("kind"):
                    problems.append(f"ratchet: changed kind {label}")
                a, b = (old, new) if slice_entry else (old.get("threshold", {}), new.get("threshold", {}))
                for threshold, direction in (("min", -1), ("max", 1), ("max_increase", 1)):
                    if threshold in a and (threshold not in b or not finite(b[threshold])
                            or direction * (b[threshold] - a[threshold]) > 0):
                        problems.append(f"ratchet: loosened {threshold} for {label}")
                if a.get("no_significant_drop") and not b.get("no_significant_drop"):
                    problems.append(f"ratchet: removed no_significant_drop for {label}")
        ratchet(base_spec.get("metrics", []), spec.get("metrics", []), lambda m: m["id"])
        ratchet(base_spec.get("slices", []), spec.get("slices", []),
                lambda s: (s["name"], s["metric"]), True)
    return list(dict.fromkeys(problems))


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for entry in spec.get("slices", []):
        mid = entry["metric"]
        sid = f"slice:{entry['name']}/{mid}"
        a, b = per_item(pr, mid, entry["name"]), per_item(base, mid, entry["name"])
        value = sum(a.values()) / len(a) if a else None
        failed = value is None or set(a) != set(b)
        note = ""
        if value is not None:
            failed |= "min" in entry and value < entry["min"]
            failed |= "max" in entry and value > entry["max"]
        if entry.get("no_significant_drop") and a and set(a) == set(b):
            keys = sorted(a)
            delta, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                confidence=bs.get("confidence", 0.95))
            note = f"Δ {delta:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            failed |= hi < 0
        if failed and entry.get("blocking"):
            blocked.append(sid)
        verdict = "BLOCK" if failed and entry.get("blocking") else "warn" if failed else "ok"
        lines.append(f"  {sid:<40} {value!s:<8} {note:<28} {verdict}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if (not pr.get("manifest", {}).get("eval_set_sha")
            or pr.get("manifest", {}).get("eval_set_sha") != base.get("manifest", {}).get("eval_set_sha")):
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid) is not None:
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
