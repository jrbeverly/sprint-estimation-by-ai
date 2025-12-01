"""Calibrate the estimator from the completed evidence records.

Deterministic arithmetic over the committed evidence produces two outputs: a
bias report (overall, per-factor, per-sprint, overrides, effort, elapsed) and
the compact guidance artifact the estimator consumes. There is no model call
in this step; the learning is the arithmetic.

Learned ratios use engineering effort only: they are computed from completed
points (the effort re-sizing recorded in the outcome) and engineering days.
Elapsed statistics are reported in their own section and never enter a
learned number.

Every generation is written under a version directory named after the sha256
of the evidence file it was calibrated from, inside the run directory; older
generations are retained. The current artifact and report are updated in
place under the current directory. Identical evidence produces byte-identical
report and artifact.
"""

import argparse
import hashlib
import json
import os

import generate

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EVIDENCE = os.path.join(ROOT, "fixtures", "evidence.json")
DEFAULT_RUN_DIR = os.path.join(ROOT, "runs")

MIN_OBSERVATIONS = 4
INSUFFICIENT = "insufficient evidence"


def load_evidence(path):
    with open(path) as handle:
        records = json.load(handle)
    if not isinstance(records, list) or not records:
        raise SystemExit("evidence must be a non-empty list of records")
    for record in records:
        problems = []
        item_id = record.get("item_id")
        if not isinstance(item_id, str):
            raise SystemExit("every evidence record must carry a string item_id")
        estimate = record.get("estimate")
        outcome = record.get("outcome")
        work_item = record.get("work_item")
        if not isinstance(estimate, dict):
            problems.append("estimate missing")
        if not isinstance(outcome, dict):
            problems.append("outcome missing")
        if not isinstance(work_item, dict):
            problems.append("work_item missing")
        if estimate and estimate.get("points") not in generate.POINTS:
            problems.append("estimate points outside the vocabulary")
        if estimate:
            for factor in estimate.get("factors") or []:
                if not isinstance(factor, dict) or factor.get("tag") not in generate.FACTORS:
                    problems.append("factor tag outside the vocabulary")
        if outcome and outcome.get("actual_points") not in generate.POINTS:
            problems.append("actual_points outside the vocabulary")
        for field in ("engineering_days", "elapsed_days"):
            value = outcome.get(field) if outcome else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append("outcome %s missing or not a number" % field)
        if work_item and not isinstance(work_item.get("sprint"), int):
            problems.append("work item sprint missing")
        override = outcome.get("override") if outcome else None
        if override is not None:
            if not isinstance(override, dict):
                problems.append("override malformed")
            else:
                if not isinstance(override.get("reason"), str) or not override["reason"].strip():
                    problems.append("override reason missing")
                if override.get("corrected_estimate") not in generate.POINTS:
                    problems.append("override corrected_estimate outside the vocabulary")
        if problems:
            raise SystemExit(
                "record %s is malformed: %s" % (item_id, "; ".join(problems))
            )
    return records


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def item_ratio(record):
    return record["outcome"]["actual_points"] / record["estimate"]["points"]


def overall_stats(evidence):
    estimated = sum(record["estimate"]["points"] for record in evidence)
    actual = sum(record["outcome"]["actual_points"] for record in evidence)
    ratios = [item_ratio(record) for record in evidence]
    return {
        "estimated_points": estimated,
        "actual_points": actual,
        "ratio": actual / estimated,
        "spread": {"min": min(ratios), "max": max(ratios)},
    }


def sprint_stats(evidence):
    buckets = {}
    for record in evidence:
        bucket = buckets.setdefault(
            record["work_item"]["sprint"],
            {"items": 0, "estimated_points": 0, "actual_points": 0},
        )
        bucket["items"] += 1
        bucket["estimated_points"] += record["estimate"]["points"]
        bucket["actual_points"] += record["outcome"]["actual_points"]
    rows = []
    for sprint in sorted(buckets):
        bucket = buckets[sprint]
        rows.append(
            {
                "sprint": sprint,
                "items": bucket["items"],
                "estimated_points": bucket["estimated_points"],
                "actual_points": bucket["actual_points"],
                "ratio": bucket["actual_points"] / bucket["estimated_points"],
            }
        )
    return rows


def factor_stats(evidence):
    ratios_by_factor = {factor: [] for factor in generate.FACTORS}
    for record in evidence:
        ratio = item_ratio(record)
        for factor in record["estimate"]["factors"]:
            ratios_by_factor[factor["tag"]].append(ratio)
    rows = []
    for factor in generate.FACTORS:
        ratios = ratios_by_factor[factor]
        if len(ratios) < MIN_OBSERVATIONS:
            rows.append(
                {
                    "factor": factor,
                    "observations": len(ratios),
                    "learned": INSUFFICIENT,
                }
            )
        else:
            rows.append(
                {
                    "factor": factor,
                    "observations": len(ratios),
                    "median_ratio": median(ratios),
                    "spread": {"min": min(ratios), "max": max(ratios)},
                }
            )
    return rows


def override_stats(evidence):
    overridden = [
        record for record in evidence if "override" in record["outcome"]
    ]
    return {
        "overridden": len(overridden),
        "total": len(evidence),
        "rate": len(overridden) / len(evidence),
        "items": [
            {
                "item_id": record["item_id"],
                "reason": record["outcome"]["override"]["reason"],
                "corrected_estimate": record["outcome"]["override"][
                    "corrected_estimate"
                ],
            }
            for record in overridden
        ],
    }


def effort_stats(evidence):
    engineering = [record["outcome"]["engineering_days"] for record in evidence]
    actual = sum(record["outcome"]["actual_points"] for record in evidence)
    total = sum(engineering)
    return {
        "engineering_days_total": total,
        "engineering_days_mean_per_item": total / len(engineering),
        "engineering_days_per_actual_point": total / actual,
    }


def elapsed_stats(evidence):
    elapsed = [record["outcome"]["elapsed_days"] for record in evidence]
    waiting = [
        record["outcome"]["elapsed_days"] - record["outcome"]["engineering_days"]
        for record in evidence
    ]
    return {
        "elapsed_days_total": sum(elapsed),
        "elapsed_days_mean_per_item": sum(elapsed) / len(elapsed),
        "waiting_days_total": sum(waiting),
        "waiting_days_mean_per_item": sum(waiting) / len(waiting),
        "waiting_days_max_per_item": max(waiting),
    }


def build_report(evidence, version):
    return {
        "version": version,
        "records": len(evidence),
        "overall": overall_stats(evidence),
        "per_sprint": sprint_stats(evidence),
        "per_factor": factor_stats(evidence),
        "overrides": override_stats(evidence),
        "effort": effort_stats(evidence),
        "elapsed": elapsed_stats(evidence),
    }


def build_artifact(report):
    lines = [
        "overall: %.3f (%d)" % (report["overall"]["ratio"], report["records"])
    ]
    by_factor = {row["factor"]: row for row in report["per_factor"]}
    for factor in generate.FACTORS:
        row = by_factor[factor]
        if "median_ratio" in row:
            lines.append(
                "%s: %.3f (%d)" % (factor, row["median_ratio"], row["observations"])
            )
        else:
            lines.append("%s: %s" % (factor, INSUFFICIENT))
    return "\n".join(lines) + "\n"


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def calibrate(evidence_path, run_dir, current_dir):
    with open(evidence_path, "rb") as handle:
        version = hashlib.sha256(handle.read()).hexdigest()
    evidence = load_evidence(evidence_path)
    report = build_report(evidence, version)
    artifact = build_artifact(report)
    generation_dir = os.path.join(run_dir, version)
    write_json(os.path.join(generation_dir, "bias-report.json"), report)
    write_text(os.path.join(generation_dir, "guidance.txt"), artifact)
    write_json(os.path.join(current_dir, "bias-report.json"), report)
    write_text(os.path.join(current_dir, "guidance.txt"), artifact)
    return report, artifact, version


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate the estimator from the completed evidence: "
        "deterministic bias report and versioned guidance artifact, no model."
    )
    parser.add_argument(
        "--evidence",
        default=DEFAULT_EVIDENCE,
        help="evidence file to calibrate from (default: fixtures/evidence.json)",
    )
    parser.add_argument(
        "--run-dir",
        default=DEFAULT_RUN_DIR,
        help="directory that retains every generation under its version "
        "(default: runs/)",
    )
    parser.add_argument(
        "--current-dir",
        default=ROOT,
        help="directory that receives the current report and artifact "
        "(default: the experiment directory)",
    )
    args = parser.parse_args()
    report, _, version = calibrate(args.evidence, args.run_dir, args.current_dir)
    print(
        "calibrated %d evidence records; version %s" % (report["records"], version)
    )


if __name__ == "__main__":
    main()
