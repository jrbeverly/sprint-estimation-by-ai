"""Compute the evaluation verdict over a recorded three-condition run.

Reads the recorded run directory (36 calls: 12 held-out backlog items x 3
conditions) plus the committed fixtures, guidance artifact, and evidence,
computes the condition metrics and the five go/no-go checks, and writes the
prose verdict and the machine-readable results under the output directory.
The verdict is pure arithmetic over the recorded calls: the run directory is
read-only, nothing is read from the environment or the network, and replaying
the run directory reproduces the same numbers without the model.

Ratio convention: sum of estimates over sum of actuals, so a calibrated
condition reads 1.0. Per-factor totals use each planted factor's held-out
items as fixed by the committed backlog estimates.
"""

import argparse
import hashlib
import json
import os

import calibrate
import generate

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(ROOT, "fixtures")
BACKLOG_PATH = os.path.join(FIXTURES, "held-out", "backlog.json")
ACTUALS_PATH = os.path.join(FIXTURES, "held-out", "held-out-actuals.json")
EVIDENCE_PATH = os.path.join(FIXTURES, "evidence.json")
GUIDANCE_PATH = os.path.join(ROOT, "guidance.txt")
DEFAULT_OUTPUT_DIR = os.path.join(ROOT, "evidence")

CONDITIONS = (
    ("unguided", None),
    ("guided", GUIDANCE_PATH),
    ("history", EVIDENCE_PATH),
)

V1_BOUNDS = (0.5, 2.0)
V2_MARGIN = 0.05
V3_RATIO_TOLERANCE = 0.05
V3_SIZE_FRACTION = 0.2
EPSILON = 1e-12


def load_json(path):
    with open(path) as handle:
        return json.load(handle)


def load_text(path):
    with open(path) as handle:
        return handle.read()


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def validate_record(record):
    problems = []
    if not isinstance(record.get("points"), int) or isinstance(
        record.get("points"), bool
    ):
        problems.append("points is not an integer")
    elif record["points"] not in generate.POINTS:
        problems.append("points %r outside the vocabulary" % record["points"])
    if record.get("confidence") not in generate.CONFIDENCE_LEVELS:
        problems.append("confidence outside low/medium/high")
    factors = record.get("factors")
    if not isinstance(factors, list) or not factors:
        problems.append("no factors")
    else:
        for factor in factors:
            if (
                not isinstance(factor, dict)
                or factor.get("tag") not in generate.FACTORS
                or not isinstance(factor.get("reason"), str)
                or not factor["reason"].strip()
            ):
                problems.append("factor outside the vocabulary or reason missing")
    if not isinstance(record.get("notes"), str) or not record["notes"].strip():
        problems.append("notes missing")
    return problems


def recorded_calls(run_dir):
    calls = {}
    root = os.path.join(run_dir, "calls")
    if not os.path.isdir(root):
        raise SystemExit("no calls/ directory under the run directory")
    for condition in sorted(os.listdir(root)):
        for item_id in sorted(os.listdir(os.path.join(root, condition))):
            calls[(condition, item_id)] = os.path.join(root, condition, item_id)
    return calls


def file_hashes(directory):
    hashes = {}
    for dirpath, _, names in os.walk(directory):
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                digest.update(handle.read())
            hashes[os.path.relpath(path, directory)] = digest.hexdigest()
    return hashes


def recalibrated_artifact():
    with open(EVIDENCE_PATH, "rb") as handle:
        version = hashlib.sha256(handle.read()).hexdigest()
    evidence = calibrate.load_evidence(EVIDENCE_PATH)
    report = calibrate.build_report(evidence, version)
    return calibrate.build_artifact(report)


def compute(run_dir, output_dir):
    run_dir = os.path.abspath(run_dir)
    output_dir = os.path.abspath(output_dir)
    if output_dir == run_dir or output_dir.startswith(run_dir + os.sep):
        raise SystemExit("the output directory must not sit inside the run directory")

    backlog = load_json(BACKLOG_PATH)
    items_by_id = {record["item_id"]: record for record in backlog["items"]}
    estimates_by_id = {record["item_id"]: record for record in backlog["estimates"]}
    actuals_by_id = {
        record["item_id"]: record for record in load_json(ACTUALS_PATH)
    }
    guidance = load_text(GUIDANCE_PATH)
    history = load_text(EVIDENCE_PATH)
    committed_context = {"unguided": None, "guided": guidance, "history": history}

    before = file_hashes(run_dir)
    calls = recorded_calls(run_dir)
    expected = {
        (condition, item_id) for condition, _ in CONDITIONS for item_id in items_by_id
    }
    present = set(calls)
    if present != expected:
        raise SystemExit(
            "the run directory must hold exactly one recorded call per "
            "condition and held-out item: missing %s, unexpected %s"
            % (sorted(expected - present), sorted(present - expected))
        )

    models = set()
    endpoints = set()
    recorded = {}
    sums = {condition: {"estimated_points": 0} for condition, _ in CONDITIONS}
    factor_items = {factor: [] for factor in generate.PLANTED}
    for item_id in items_by_id:
        tags = [factor["tag"] for factor in estimates_by_id[item_id]["factors"]]
        for factor in generate.PLANTED:
            if factor in tags:
                factor_items[factor].append(item_id)
    for (condition, item_id), directory in sorted(calls.items()):
        for name in ("request.json", "response.json", "estimate.json"):
            path = os.path.join(directory, name)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise SystemExit("missing or empty %s for %s/%s" % (name, condition, item_id))
        request = load_json(os.path.join(directory, "request.json"))
        estimate = load_json(os.path.join(directory, "estimate.json"))
        if request.get("condition") != condition:
            raise SystemExit(
                "recorded request condition differs for %s/%s" % (condition, item_id)
            )
        if request.get("item") != items_by_id[item_id]:
            raise SystemExit(
                "recorded request item differs from the committed backlog item %s"
                % item_id
            )
        if request.get("guidance") != committed_context[condition]:
            raise SystemExit(
                "recorded %s context differs from the committed %s"
                % (condition, "artifact" if condition == "guided" else "evidence")
            )
        models.add(request.get("model"))
        endpoints.add(request.get("endpoint"))
        problems = validate_record(estimate)
        if problems:
            raise SystemExit(
                "invalid recorded estimate for %s/%s: %s"
                % (condition, item_id, "; ".join(problems))
            )
        if estimate.get("item_id") != item_id:
            raise SystemExit(
                "recorded estimate item_id differs for %s/%s" % (condition, item_id)
            )
        recorded[(condition, item_id)] = estimate
        sums[condition]["estimated_points"] += estimate["points"]
    if len(models) != 1 or None in models or len(endpoints) != 1 or None in endpoints:
        raise SystemExit("the recorded calls span more than one model or endpoint")

    actual_points_all = sum(
        actuals_by_id[item_id]["actual_points"] for item_id in items_by_id
    )
    conditions = {}
    for condition, _ in CONDITIONS:
        conditions[condition] = {
            "estimated_points": sums[condition]["estimated_points"],
            "actual_points": actual_points_all,
            "total_ratio": sums[condition]["estimated_points"] / actual_points_all,
        }
    per_factor = {}
    for factor in generate.PLANTED:
        ids = sorted(factor_items[factor])
        if len(ids) != 3:
            raise SystemExit(
                "factor %s covers %d held-out items, expected 3" % (factor, len(ids))
            )
        actual = sum(actuals_by_id[item_id]["actual_points"] for item_id in ids)
        row = {"items": len(ids), "actual_points": actual}
        for condition, _ in CONDITIONS:
            estimated = sum(recorded[(condition, item_id)]["points"] for item_id in ids)
            row[condition] = {
                "estimated_points": estimated,
                "ratio": estimated / actual,
            }
        per_factor[factor] = row
    sizes = {
        "artifact_chars": len(guidance),
        "history_context_chars": len(history),
        "artifact_fraction": len(guidance) / len(history),
    }

    guidance_match = recalibrated_artifact() == guidance
    after = file_hashes(run_dir)
    modified_files = len(
        sorted(
            path for path in before if before[path] != after.get(path)
        )
        + sorted(path for path in after if path not in before)
    )

    checks = evaluate_checks(conditions, per_factor, sizes, guidance_match, modified_files, len(calls))
    overall = {
        "pass": all(check["pass"] for check in checks.values()),
        "passed": sum(1 for check in checks.values() if check["pass"]),
        "total": len(checks),
    }
    return {
        "metrics": {"conditions": conditions, "per_factor": per_factor, "sizes": sizes},
        "checks": checks,
        "overall": overall,
    }


def evaluate_checks(conditions, per_factor, sizes, guidance_match, modified_files, total_estimates):
    unguided = conditions["unguided"]["total_ratio"]
    guided = conditions["guided"]["total_ratio"]
    history = conditions["history"]["total_ratio"]
    v1 = {
        "check": "baseline sanity",
        "pass": V1_BOUNDS[0] <= unguided <= V1_BOUNDS[1],
        "numbers": {
            "unguided_total_ratio": unguided,
            "bounds": list(V1_BOUNDS),
        },
    }
    unguided_distance = abs(unguided - 1.0)
    guided_distance = abs(guided - 1.0)
    v2 = {
        "check": "learning transfers",
        "pass": guided_distance + V2_MARGIN <= unguided_distance + EPSILON,
        "numbers": {
            "unguided_distance": unguided_distance,
            "guided_distance": guided_distance,
            "margin": unguided_distance - guided_distance,
            "required": V2_MARGIN,
        },
    }
    ratio_difference = abs(guided - history)
    v3 = {
        "check": "compaction",
        "pass": ratio_difference <= V3_RATIO_TOLERANCE + EPSILON
        and sizes["artifact_fraction"] <= V3_SIZE_FRACTION + EPSILON,
        "numbers": {
            "guided_history_ratio_difference": ratio_difference,
            "max_ratio_difference": V3_RATIO_TOLERANCE,
            "artifact_chars": sizes["artifact_chars"],
            "history_context_chars": sizes["history_context_chars"],
            "artifact_fraction": sizes["artifact_fraction"],
            "max_artifact_fraction": V3_SIZE_FRACTION,
        },
    }
    factor_numbers = {}
    for factor, row in per_factor.items():
        factor_numbers[factor] = {
            "unguided_ratio": row["unguided"]["ratio"],
            "guided_ratio": row["guided"]["ratio"],
            "unguided_distance": abs(row["unguided"]["ratio"] - 1.0),
            "guided_distance": abs(row["guided"]["ratio"] - 1.0),
        }
    v4 = {
        "check": "bias recovery",
        "pass": all(
            numbers["guided_distance"] < numbers["unguided_distance"]
            for numbers in factor_numbers.values()
        ),
        "numbers": factor_numbers,
    }
    v5 = {
        "check": "guardrails",
        "pass": total_estimates == 36 and guidance_match and modified_files == 0,
        "numbers": {
            "estimates_in_vocabulary": "%d/%d" % (total_estimates, total_estimates),
            "guidance_matches_recalibration": guidance_match,
            "run_dir_files_modified_by_evaluation": modified_files,
        },
    }
    return {"V1": v1, "V2": v2, "V3": v3, "V4": v4, "V5": v5}


def render_verdict(results):
    metrics = results["metrics"]
    sizes = metrics["sizes"]
    checks = results["checks"]
    overall = results["overall"]
    lines = [
        "# Evaluation verdict — guided and unguided estimation on the held-out backlog",
        "",
        "Computed from the recorded run directory (36 calls: 12 held-out items x",
        "3 conditions) and the committed fixtures; replaying the run directory",
        "without the model reproduces these numbers exactly.",
        "",
        "Condition totals (ratio = sum of estimates / sum of actuals):",
        "",
    ]
    for condition, row in metrics["conditions"].items():
        lines.append(
            "- %s: estimated %d, actual %d, total ratio %.3f"
            % (condition, row["estimated_points"], row["actual_points"], row["total_ratio"])
        )
    lines.append("")
    lines.append("Per-factor totals (each planted factor's three held-out items):")
    lines.append("")
    for factor, row in metrics["per_factor"].items():
        lines.append(
            "- %s: actual %d; unguided ratio %.3f, guided ratio %.3f, "
            "history ratio %.3f"
            % (
                factor,
                row["actual_points"],
                row["unguided"]["ratio"],
                row["guided"]["ratio"],
                row["history"]["ratio"],
            )
        )
    lines.append("")
    lines.append(
        "Context sizes: artifact %d characters, raw history %d characters "
        "(fraction %.4f)."
        % (sizes["artifact_chars"], sizes["history_context_chars"], sizes["artifact_fraction"])
    )
    lines.append("")
    for key in ("V1", "V2", "V3", "V4", "V5"):
        check = checks[key]
        lines.append("## %s %s — %s" % (key, check["check"], "PASS" if check["pass"] else "FAIL"))
        lines.append("")
        lines.append("Numbers: %s" % check_lines(key, check))
        lines.append("")
    lines.append("## Overall verdict")
    lines.append("")
    lines.append(
        "**%s** — %d of %d checks passed."
        % ("PASS" if overall["pass"] else "FAIL", overall["passed"], overall["total"])
    )
    lines.append("")
    return "\n".join(lines)


def check_lines(key, check):
    numbers = check["numbers"]
    if key == "V1":
        return "unguided total ratio %.3f; bounds [%.1f, %.1f]" % (
            numbers["unguided_total_ratio"],
            numbers["bounds"][0],
            numbers["bounds"][1],
        )
    if key == "V2":
        return (
            "unguided distance %.3f, guided distance %.3f; margin %.3f "
            "(required %.2f)"
            % (
                numbers["unguided_distance"],
                numbers["guided_distance"],
                numbers["margin"],
                numbers["required"],
            )
        )
    if key == "V3":
        return (
            "guided-vs-history ratio difference %.3f (max %.2f); artifact %d "
            "characters, history %d characters (fraction %.4f, max %.1f)"
            % (
                numbers["guided_history_ratio_difference"],
                numbers["max_ratio_difference"],
                numbers["artifact_chars"],
                numbers["history_context_chars"],
                numbers["artifact_fraction"],
                numbers["max_artifact_fraction"],
            )
        )
    if key == "V4":
        parts = []
        for factor, row in numbers.items():
            parts.append(
                "%s unguided %.3f -> guided %.3f"
                % (factor, row["unguided_ratio"], row["guided_ratio"])
            )
        return "; ".join(parts)
    return (
        "estimates in vocabulary %s; guidance matches deterministic "
        "recalibration over the committed evidence: %s; run directory files "
        "modified by the evaluation: %d"
        % (
            numbers["estimates_in_vocabulary"],
            "yes" if numbers["guidance_matches_recalibration"] else "no",
            numbers["run_dir_files_modified_by_evaluation"],
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Compute the evaluation verdict over a recorded run "
        "directory: condition metrics, the five go/no-go checks, and the "
        "prose and machine-readable results."
    )
    parser.add_argument("--run-dir", required=True, help="directory holding the 36 recorded calls")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="directory that receives verdict.md and results.json "
        "(default: evidence/)",
    )
    args = parser.parse_args()
    results = compute(args.run_dir, args.output_dir)
    write_json(os.path.join(args.output_dir, "results.json"), results)
    write_text(os.path.join(args.output_dir, "verdict.md"), render_verdict(results))
    for condition, row in results["metrics"]["conditions"].items():
        print(
            "%-9s total ratio %.4f (estimated %d / actual %d)"
            % (condition, row["total_ratio"], row["estimated_points"], row["actual_points"])
        )
    for key in ("V1", "V2", "V3", "V4", "V5"):
        check = results["checks"][key]
        print("%s %-17s %s" % (key, check["check"], "PASS" if check["pass"] else "FAIL"))
    overall = results["overall"]
    print("overall: %s (%d/%d)" % ("PASS" if overall["pass"] else "FAIL", overall["passed"], overall["total"]))


if __name__ == "__main__":
    main()
