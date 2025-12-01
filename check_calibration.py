"""Validate the calibration step against its acceptance criteria: planted
multiplier and weighted-plant recovery, the fixed artifact shape, the
insufficient-evidence rule, elapsed-only invariance of the learned ratios,
byte-identical determinism with retained generations, the override rate, the
per-sprint totals, the absence of per-item ranking, and step hygiene (no
model call, no network, no sibling imports).
"""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import generate

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(ROOT, "fixtures")
CALIBRATE = os.path.join(ROOT, "calibrate.py")
EVIDENCE_PATH = os.path.join(FIXTURES, "evidence.json")
HELD_OUT_ACTUALS_NAME = "held-out-actuals.json"
MIN_OBSERVATIONS = 4

failures = []


def report(ok, message):
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        failures.append(message)


def load(path):
    with open(path) as handle:
        return json.load(handle)


def walk_json(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def dump(payload, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def run_calibrate(evidence_path, run_dir, current_dir):
    result = subprocess.run(
        [
            sys.executable,
            CALIBRATE,
            "--evidence",
            evidence_path,
            "--run-dir",
            run_dir,
            "--current-dir",
            current_dir,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        report(
            False,
            "calibrate failed over %s: %s"
            % (os.path.basename(evidence_path), result.stderr.strip()),
        )
        return None
    return result.stdout.strip()


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def weighted_plant(evidence):
    estimated = sum(record["estimate"]["points"] for record in evidence)
    weighted = 0
    for record in evidence:
        planted = next(
            (
                factor["tag"]
                for factor in record["estimate"]["factors"]
                if factor["tag"] in generate.PLANTED
            ),
            None,
        )
        multiplier = (
            generate.PLANTED[planted]["multiplier"]
            if planted
            else generate.NEUTRAL_RULE["multiplier"]
        )
        weighted += record["estimate"]["points"] * multiplier
    return weighted / estimated


def artifact_lines(path):
    with open(path) as handle:
        return handle.read().splitlines()


def factor_rows(report):
    return {row["factor"]: row for row in report["per_factor"]}


def main():
    # Criterion 8: the step is plain arithmetic over the committed evidence.
    with open(CALIBRATE) as handle:
        source = handle.read()
        tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"requests", "urllib", "http", "socket", "ftplib", "jira", "acli"}
    report(
        not (imported & banned),
        "calibrate.py imports none of the network or Jira modules",
    )
    local = sorted(imported - set(sys.stdlib_module_names))
    report(
        local == ["generate"],
        "calibrate.py imports only the standard library and the sibling "
        "generator, not other experiments (%s)" % ", ".join(local),
    )
    report(
        "https://" not in source and HELD_OUT_ACTUALS_NAME not in source,
        "calibrate.py commits no endpoint and never reads the held-out actuals",
    )

    # Criterion 1 and 5: run over the committed evidence and compare against
    # the committed outputs, the planted multipliers, and the weighted plant.
    tmp = tempfile.mkdtemp(prefix="sprint-estimation-calibration-")
    try:
        run_dir = os.path.join(tmp, "runs")
        for name in ("first", "second"):
            run_calibrate(EVIDENCE_PATH, run_dir, os.path.join(tmp, name))
        report(
            read_bytes(os.path.join(tmp, "first", "guidance.txt"))
            == read_bytes(os.path.join(tmp, "second", "guidance.txt"))
            and read_bytes(os.path.join(tmp, "first", "bias-report.json"))
            == read_bytes(os.path.join(tmp, "second", "bias-report.json")),
            "two runs over identical evidence produce byte-identical "
            "report and artifact",
        )
        committed_version = hashlib.sha256(read_bytes(EVIDENCE_PATH)).hexdigest()
        committed_run = os.path.join(ROOT, "runs", committed_version)
        for name in ("guidance.txt", "bias-report.json"):
            report(
                os.path.isfile(os.path.join(ROOT, name)),
                "committed %s exists" % name,
            )
            report(
                read_bytes(os.path.join(ROOT, name))
                == read_bytes(os.path.join(tmp, "first", name)),
                "committed %s matches a fresh run over the committed evidence"
                % name,
            )
            report(
                os.path.isfile(os.path.join(committed_run, name))
                and read_bytes(os.path.join(committed_run, name))
                == read_bytes(os.path.join(ROOT, name)),
                "the committed generation under runs/%s matches the current "
                "copy" % committed_version[:12],
            )
        version_dirs = sorted(
            name for name in os.listdir(os.path.join(ROOT, "runs"))
        )
        report(
            version_dirs == [committed_version],
            "the run directory holds exactly the committed-evidence generation",
        )
        report_path = os.path.join(tmp, "first", "bias-report.json")
        report_data = load(report_path)
        evidence = load(EVIDENCE_PATH)

        print("learned values over the committed fixture:")
        planted_rows = {
            factor: factor_rows(report_data)[factor]
            for factor in generate.PLANTED
        }
        for factor, planted in generate.PLANTED.items():
            row = planted_rows[factor]
            distance = abs(row["median_ratio"] - planted["multiplier"])
            report(
                row["observations"] >= 6 and distance <= 0.1,
                "  %-22s n=%d median=%.4g planted=%.1f (distance %.4g)"
                % (
                    factor,
                    row["observations"],
                    row["median_ratio"],
                    planted["multiplier"],
                    distance,
                ),
            )
        overall = report_data["overall"]
        plant = weighted_plant(evidence)
        distance = abs(overall["ratio"] - plant)
        report(
            distance <= 0.1,
            "overall ratio %.4g matches the weighted plant %.4g "
            "(distance %.4g)" % (overall["ratio"], plant, distance),
        )
        item_ratios = [
            record["outcome"]["actual_points"] / record["estimate"]["points"]
            for record in evidence
        ]
        report(
            overall["spread"] == {"min": min(item_ratios), "max": max(item_ratios)}
            and overall["estimated_points"]
            == sum(record["estimate"]["points"] for record in evidence)
            and overall["actual_points"]
            == sum(record["outcome"]["actual_points"] for record in evidence),
            "overall totals and the spread of per-item ratios match the fixture",
        )

        # Criterion 2: the artifact has exactly one line per vocabulary
        # factor plus the overall line.
        lines = artifact_lines(os.path.join(tmp, "first", "guidance.txt"))
        report(
            len(lines) == 1 + len(generate.FACTORS)
            and lines[0].startswith("overall: ")
            and [line.split(":")[0] for line in lines[1:]]
            == list(generate.FACTORS),
            "the artifact holds exactly the overall line plus one line per "
            "vocabulary factor, in vocabulary order",
        )
        learned_line = re.compile(r"^[a-z-]+: \d+\.\d{3} \(\d+\)$")
        report(
            all(learned_line.match(line) for line in lines),
            "every factor in the committed fixture is learned as "
            "ratio + evidence count",
        )
        report(
            "SYN-" not in "\n".join(lines),
            "the artifact carries no per-item content",
        )

        # Criterion 7: per-sprint table with the same 8 sprints and matching
        # totals.
        expected_sprints = []
        for sprint in range(1, 9):
            records = [
                record
                for record in evidence
                if record["work_item"]["sprint"] == sprint
            ]
            expected_sprints.append(
                {
                    "sprint": sprint,
                    "items": len(records),
                    "estimated_points": sum(
                        record["estimate"]["points"] for record in records
                    ),
                    "actual_points": sum(
                        record["outcome"]["actual_points"] for record in records
                    ),
                    "ratio": sum(
                        record["outcome"]["actual_points"] for record in records
                    )
                    / sum(record["estimate"]["points"] for record in records),
                }
            )
        report(
            report_data["per_sprint"] == expected_sprints,
            "the per-sprint table shows the same 8 sprints as the fixture "
            "with matching estimated and actual totals",
        )
        for row in report_data["per_sprint"]:
            print(
                "  sprint %d: items=%d estimated=%d actual=%d ratio=%.4g"
                % (
                    row["sprint"],
                    row["items"],
                    row["estimated_points"],
                    row["actual_points"],
                    row["ratio"],
                )
            )

        # Criterion 6: override rate equals overrides/total computed by hand.
        overridden_ids = [
            record["item_id"]
            for record in evidence
            if "override" in record["outcome"]
        ]
        hand_rate = len(overridden_ids) / len(evidence)
        overrides = report_data["overrides"]
        report(
            overrides["rate"] == hand_rate
            and overrides["overridden"] == len(overridden_ids)
            and overrides["total"] == len(evidence),
            "override rate %g equals %d/%d computed by hand"
            % (overrides["rate"], len(overridden_ids), len(evidence)),
        )
        report(
            [item["item_id"] for item in overrides["items"]] == overridden_ids
            and all(
                item["reason"]
                and item["corrected_estimate"] == next(
                    record["outcome"]["actual_points"]
                    for record in evidence
                    if record["item_id"] == item["item_id"]
                )
                for item in overrides["items"]
            ),
            "the overriding items are listed with their reasons and corrected "
            "estimates",
        )

        # No per-item optimization, retraining, or individual ranking: item
        # ids appear only as the required overriding-items list.
        strings = [
            value
            for node in walk_json(report_data)
            if isinstance(node, dict)
            for value in node.values()
            if isinstance(value, str)
        ]
        item_id_strings = {
            value for value in strings if re.match(r"^SYN-\d+$", value)
        }
        report(
            item_id_strings == set(overridden_ids),
            "no individual ranking anywhere: the only item ids in the report "
            "are the overriding items",
        )

        # Criterion 2 (extension): a ninth sprint of evidence leaves the
        # artifact line count unchanged, and the earlier generation survives.
        backlog = load(os.path.join(FIXTURES, "held-out", "backlog.json"))
        held_actuals = load(
            os.path.join(FIXTURES, "held-out", HELD_OUT_ACTUALS_NAME)
        )
        items_by_id = {record["item_id"]: record for record in backlog["items"]}
        estimates_by_id = {
            record["item_id"]: record for record in backlog["estimates"]
        }
        actuals_by_id = {
            record["item_id"]: record for record in held_actuals
        }
        extended = list(evidence)
        for item_id in sorted(items_by_id):
            extended.append(
                {
                    "item_id": item_id,
                    "work_item": items_by_id[item_id],
                    "estimate": estimates_by_id[item_id],
                    "outcome": actuals_by_id[item_id],
                }
            )
        extension_path = os.path.join(tmp, "evidence-extension.json")
        dump(extended, extension_path)
        run_calibrate(extension_path, run_dir, os.path.join(tmp, "extended"))
        extended_lines = artifact_lines(
            os.path.join(tmp, "extended", "guidance.txt")
        )
        report(
            len(extended_lines) == len(lines) == 10,
            "a ninth sprint of evidence leaves the artifact line count at %d"
            % len(lines),
        )
        report(
            os.path.isdir(committed_run)
            and read_bytes(
                os.path.join(run_dir, committed_version, "guidance.txt")
            )
            == read_bytes(os.path.join(tmp, "first", "guidance.txt")),
            "the previous generation still exists in the run directory after "
            "regeneration over the extension",
        )
        extended_report = load(os.path.join(tmp, "extended", "bias-report.json"))
        report(
            [row["sprint"] for row in extended_report["per_sprint"]]
            == list(range(1, 10)),
            "the extension report adds sprint 9 to the per-sprint table",
        )

        # The step's boundary: malformed evidence is refused loudly, naming
        # the record, instead of learning from it.
        malformed = json.loads(json.dumps(evidence))
        malformed[3]["outcome"]["actual_points"] = 4  # outside the vocabulary
        malformed_path = os.path.join(tmp, "evidence-malformed.json")
        dump(malformed, malformed_path)
        refused = subprocess.run(
            [
                sys.executable,
                CALIBRATE,
                "--evidence",
                malformed_path,
                "--run-dir",
                run_dir,
                "--current-dir",
                os.path.join(tmp, "malformed"),
            ],
            capture_output=True,
            text=True,
        )
        report(
            refused.returncode != 0
            and "SYN-104" in refused.stderr
            and "actual_points" in refused.stderr,
            "malformed evidence is refused, naming the record and the problem",
        )

        # Criterion 3: fewer than 4 observations means insufficient evidence
        # with no learned ratio.
        reduced_path = os.path.join(tmp, "evidence-reduced.json")
        dump(evidence[:10], reduced_path)
        run_calibrate(reduced_path, run_dir, os.path.join(tmp, "reduced"))
        reduced_lines = artifact_lines(
            os.path.join(tmp, "reduced", "guidance.txt")
        )
        reduced_report = load(os.path.join(tmp, "reduced", "bias-report.json"))
        short_factors = [
            row["factor"]
            for row in reduced_report["per_factor"]
            if row["observations"] < MIN_OBSERVATIONS
        ]
        report(
            short_factors,
            "the reduced fixture leaves at least one factor below %d "
            "observations" % MIN_OBSERVATIONS,
        )
        by_line = {
            line.split(":")[0]: line for line in reduced_lines
        }
        bad = []
        for row in reduced_report["per_factor"]:
            if row["observations"] < MIN_OBSERVATIONS:
                if row.get("learned") != "insufficient evidence":
                    bad.append(row["factor"] + ": report")
                if "median_ratio" in row or "spread" in row:
                    bad.append(row["factor"] + ": ratio")
                if by_line.get(row["factor"]) != (
                    row["factor"] + ": insufficient evidence"
                ):
                    bad.append(row["factor"] + ": artifact")
            else:
                if not learned_line.match(by_line.get(row["factor"], "")):
                    bad.append(row["factor"] + ": artifact")
        report(
            not bad,
            "factors below %d observations read 'insufficient evidence' with "
            "no learned ratio (%s)"
            % (MIN_OBSERVATIONS, "; ".join(bad) if bad else "all correct"),
        )

        # Criterion 4: elapsed-only data leaves every learned ratio
        # byte-identical; only the elapsed section moves.
        elapsed_path = os.path.join(tmp, "evidence-elapsed.json")
        elapsed_variant = json.loads(json.dumps(evidence))
        elapsed_variant[0]["outcome"]["elapsed_days"] += 5.0
        dump(elapsed_variant, elapsed_path)
        run_calibrate(elapsed_path, run_dir, os.path.join(tmp, "elapsed"))
        report(
            read_bytes(os.path.join(tmp, "elapsed", "guidance.txt"))
            == read_bytes(os.path.join(tmp, "first", "guidance.txt")),
            "a blocked item with 5 extra elapsed days and unchanged effort "
            "leaves the artifact byte-identical",
        )
        elapsed_report = load(os.path.join(tmp, "elapsed", "bias-report.json"))
        learned_sections = (
            "records",
            "overall",
            "per_sprint",
            "per_factor",
            "overrides",
            "effort",
        )
        report(
            all(
                elapsed_report[section] == report_data[section]
                for section in learned_sections
            ),
            "the report's learned sections are unchanged by elapsed-only data",
        )
        report(
            abs(
                elapsed_report["elapsed"]["elapsed_days_total"]
                - report_data["elapsed"]["elapsed_days_total"]
                - 5.0
            )
            < 1e-9
            and elapsed_report["effort"] == report_data["effort"],
            "only the separate elapsed section reflects the added elapsed days",
        )
    finally:
        shutil.rmtree(tmp)

    print()
    if failures:
        print("%d check(s) failed" % len(failures))
        sys.exit(1)
    print("all calibration checks passed")


if __name__ == "__main__":
    main()
