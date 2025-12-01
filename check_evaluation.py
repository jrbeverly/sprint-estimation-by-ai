"""Validate the evaluation step against its acceptance criteria: the committed
verdict files carry the same numbers and pass/fail decisions, the recorded run
directory holds exactly 36 calls, replaying it without the model reproduces
the verdict exactly, and the evaluation is aggregate-only hygiene (no
environment, no network, no day fields, read-only over the run directory).
Includes a live batch run.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import evaluate
import generate

ROOT = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_DIR = os.path.join(ROOT, "evidence")
VERDICT_PATH = os.path.join(EVIDENCE_DIR, "verdict.md")
RESULTS_PATH = os.path.join(EVIDENCE_DIR, "results.json")
EVALUATE = os.path.join(ROOT, "evaluate.py")
BATCH = os.path.join(ROOT, "run_batch.py")
ESTIMATE = os.path.join(ROOT, "estimate.py")
BACKLOG_PATH = os.path.join(ROOT, "fixtures", "held-out", "backlog.json")
ACTUALS_PATH = os.path.join(
    ROOT, "fixtures", "held-out", "held-out-actuals.json"
)
HELD_OUT_ACTUALS_NAME = "held-out-actuals.json"
CONDITIONS = ("unguided", "guided", "history")

failures = []


def report(ok, message):
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        failures.append(message)


def load(path):
    with open(path) as handle:
        return json.load(handle)


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def scrub_env():
    env = dict(os.environ)
    for name in list(env):
        if name.startswith("ANTHROPIC"):
            del env[name]
    return env


def expected_decision(key, checks):
    numbers = checks[key]["numbers"]
    if key == "V1":
        low, high = numbers["bounds"]
        return low <= numbers["unguided_total_ratio"] <= high
    if key == "V2":
        return numbers["guided_distance"] + 0.05 <= numbers["unguided_distance"] + 1e-12
    if key == "V3":
        return (
            numbers["guided_history_ratio_difference"] <= 0.05 + 1e-12
            and numbers["artifact_fraction"] <= 0.2 + 1e-12
        )
    if key == "V4":
        return all(
            row["guided_distance"] < row["unguided_distance"]
            for row in numbers.values()
        )
    return (
        numbers["estimates_in_vocabulary"] == "36/36"
        and numbers["guidance_matches_recalibration"] is True
        and numbers["run_dir_files_modified_by_evaluation"] == 0
    )


def recorded_estimate(run_dir, condition, item_id):
    return load(
        os.path.join(run_dir, "calls", condition, item_id, "estimate.json")
    )


def main():
    # Criterion 1: the committed verdict files exist and agree with each
    # other, and every pass/fail follows its numbers.
    report(
        os.path.isfile(VERDICT_PATH) and os.path.isfile(RESULTS_PATH),
        "committed evidence/verdict.md and evidence/results.json exist",
    )
    if os.path.isfile(RESULTS_PATH) and os.path.isfile(VERDICT_PATH):
        results = load(RESULTS_PATH)
        verdict = read_bytes(VERDICT_PATH).decode()
        report(
            sorted(results) == ["checks", "metrics", "overall"],
            "results.json holds the metrics, checks, and overall sections",
        )
        report(
            sorted(results["checks"]) == ["V1", "V2", "V3", "V4", "V5"],
            "results.json holds exactly the five checks",
        )
        report(
            evaluate.render_verdict(results) == verdict,
            "the prose verdict renders from the machine-readable results, so "
            "both carry the same numbers",
        )
        for key in ("V1", "V2", "V3", "V4", "V5"):
            check = results["checks"][key]
            match = re.search(
                r"^## %s [^\n]+ — (PASS|FAIL)$" % key, verdict, re.M
            )
            stated = "PASS" if check["pass"] else "FAIL"
            report(
                match is not None and match.group(1) == stated,
                "verdict.md states %s as %s" % (key, stated),
            )
            report(
                expected_decision(key, results["checks"]) == check["pass"],
                "%s pass/fail follows its measured numbers" % key,
            )
        overall = results["overall"]
        match = re.search(
            r"^\*\*(PASS|FAIL)\*\* — (\d+) of (\d+) checks passed\.$",
            verdict,
            re.M,
        )
        stated = "PASS" if overall["pass"] else "FAIL"
        report(
            match is not None
            and match.group(1) == stated
            and int(match.group(2)) == overall["passed"]
            and int(match.group(3)) == overall["total"]
            and overall["pass"] == all(
                results["checks"][key]["pass"]
                for key in ("V1", "V2", "V3", "V4", "V5")
            ),
            "the overall verdict agrees with the per-check results",
        )
        report(
            "SYN-" not in verdict and "SYN-" not in json.dumps(results),
            "the committed verdict files carry no held-out ids",
        )

    # Criterion 2: evaluate.py is aggregate-only hygiene.
    with open(EVALUATE) as handle:
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
        "evaluate.py imports none of the network or Jira modules",
    )
    local = sorted(imported - set(sys.stdlib_module_names))
    report(
        local == ["calibrate", "generate"],
        "evaluate.py imports only the standard library and its sibling "
        "modules (%s)" % ", ".join(local),
    )
    report(
        "os.environ" not in source and "https://" not in source,
        "evaluate.py reads no environment and commits no endpoint",
    )
    report(
        "elapsed" not in source and "engineering" not in source,
        "evaluate.py mixes no day fields into the learned numbers",
    )
    report(
        HELD_OUT_ACTUALS_NAME in source,
        "evaluate.py is the step that reads the held-out actuals",
    )
    for script in ("generate.py", "estimate.py", "run_batch.py", "calibrate.py"):
        with open(os.path.join(ROOT, script)) as handle:
            text = handle.read()
        report(
            HELD_OUT_ACTUALS_NAME not in text,
            "%s never reads the held-out actuals" % script,
        )

    # Criteria 3-6: live batch, evaluate, independent recomputation, replay
    # without the model.
    tmp = tempfile.mkdtemp(prefix="sprint-estimation-eval-")
    try:
        run_dir = os.path.join(tmp, "run")
        print("running the live batch (36 calls, may take a while)...")
        batch = subprocess.run(
            [sys.executable, BATCH, "--run-dir", run_dir],
            capture_output=True,
            text=True,
        )
        detail = batch.stderr.strip()
        report(
            batch.returncode == 0,
            "live batch run succeeds%s" % (": " + detail[-200:] if detail else ""),
        )
        if batch.returncode == 0:
            calls = evaluate.recorded_calls(run_dir)
            report(
                len(calls) == 36,
                "36 recorded calls (12 items x 3 conditions), got %d" % len(calls),
            )
            per_condition = {}
            for condition, _ in calls:
                per_condition[condition] = per_condition.get(condition, 0) + 1
            report(
                per_condition == {"guided": 12, "history": 12, "unguided": 12},
                "12 calls per condition (%s)"
                % ", ".join(
                    "%s=%d" % item for item in sorted(per_condition.items())
                ),
            )
            models = set()
            endpoints = set()
            empty = []
            for condition, item_id in calls:
                directory = os.path.join(run_dir, "calls", condition, item_id)
                request = load(os.path.join(directory, "request.json"))
                models.add(request.get("model"))
                endpoints.add(request.get("endpoint"))
                for name in ("request.json", "response.json", "estimate.json"):
                    if os.path.getsize(os.path.join(directory, name)) == 0:
                        empty.append((condition, item_id))
            report(
                not empty and len(models) == 1 and None not in models
                and len(endpoints) == 1 and None not in endpoints,
                "every call recorded a request, response, and estimate under "
                "one model and endpoint",
            )

            evidence_before = evaluate.file_hashes(EVIDENCE_DIR)
            before = evaluate.file_hashes(run_dir)
            out1 = os.path.join(tmp, "out1")
            live = subprocess.run(
                [sys.executable, EVALUATE, "--run-dir", run_dir, "--output-dir", out1],
                capture_output=True,
                text=True,
            )
            report(
                live.returncode == 0,
                "evaluate.py runs over the recorded run directory%s"
                % (": " + live.stderr.strip()[-200:] if live.stderr.strip() else ""),
            )
            if live.returncode == 0:
                report(
                    sorted(os.listdir(out1)) == ["results.json", "verdict.md"],
                    "evaluate.py writes exactly results.json and verdict.md",
                )
                report(
                    evaluate.file_hashes(run_dir) == before,
                    "evaluate.py leaves the run directory byte-identical "
                    "(no per-item optimization)",
                )
                report(
                    evaluate.file_hashes(EVIDENCE_DIR) == evidence_before,
                    "evaluate.py leaves the committed evidence/ directory "
                    "untouched when writing elsewhere",
                )
                results1 = load(os.path.join(out1, "results.json"))
                report(
                    evaluate.render_verdict(results1)
                    == read_bytes(os.path.join(out1, "verdict.md")).decode(),
                    "the generated prose verdict matches the generated results",
                )

                # Independent recomputation from the raw recorded files.
                backlog = load(BACKLOG_PATH)
                items_by_id = {r["item_id"]: r for r in backlog["items"]}
                estimates_by_id = {
                    r["item_id"]: r for r in backlog["estimates"]
                }
                actuals_by_id = {r["item_id"]: r for r in load(ACTUALS_PATH)}
                actual_all = sum(
                    row["actual_points"] for row in actuals_by_id.values()
                )
                match = True
                for condition in CONDITIONS:
                    estimated = sum(
                        recorded_estimate(run_dir, condition, item_id)["points"]
                        for item_id in items_by_id
                    )
                    row = results1["metrics"]["conditions"][condition]
                    if row["estimated_points"] != estimated or row["actual_points"] != actual_all:
                        match = False
                        report(
                            False,
                            "%s totals differ from the raw recorded calls" % condition,
                        )
                    if row["total_ratio"] != estimated / actual_all:
                        match = False
                        report(
                            False,
                            "%s total ratio differs from the raw recorded calls"
                            % condition,
                        )
                for factor in generate.PLANTED:
                    ids = sorted(
                        item_id
                        for item_id, estimate in estimates_by_id.items()
                        if any(
                            f["tag"] == factor for f in estimate["factors"]
                        )
                    )
                    actual = sum(actuals_by_id[i]["actual_points"] for i in ids)
                    for condition in CONDITIONS:
                        estimated = sum(
                            recorded_estimate(run_dir, condition, item_id)["points"]
                            for item_id in ids
                        )
                        row = results1["metrics"]["per_factor"][factor][condition]
                        if (
                            row["estimated_points"] != estimated
                            or row["ratio"] != estimated / actual
                        ):
                            match = False
                            report(
                                False,
                                "%s %s ratio differs from the raw recorded calls"
                                % (factor, condition),
                            )
                if match:
                    report(
                        True,
                        "every number in results.json matches an independent "
                        "recomputation from the raw recorded calls",
                    )

            # Replay: no model, no network; the same verdict comes out.
            print("replaying the run directory with the model unavailable...")
            identical = 0
            for condition, item_id in calls:
                directory = os.path.join(run_dir, "calls", condition, item_id)
                request = load(os.path.join(directory, "request.json"))
                item_path = os.path.join(tmp, "replay-item.json")
                with open(item_path, "w") as handle:
                    json.dump(request["item"], handle)
                command = [
                    sys.executable,
                    ESTIMATE,
                    "--item",
                    item_path,
                    "--condition",
                    condition,
                    "--run-dir",
                    run_dir,
                    "--replay",
                ]
                if request.get("guidance") is not None:
                    guidance_path = os.path.join(tmp, "replay-guidance.txt")
                    with open(guidance_path, "w") as handle:
                        handle.write(request["guidance"])
                    command += ["--guidance", guidance_path]
                replay = subprocess.run(
                    command, capture_output=True, text=True, env=scrub_env()
                )
                if replay.returncode != 0:
                    report(
                        False,
                        "replay failed for %s/%s: %s"
                        % (condition, item_id, replay.stderr.strip()),
                    )
                    continue
                stored = read_bytes(os.path.join(directory, "estimate.json"))
                if replay.stdout.encode() == stored:
                    identical += 1
                else:
                    report(False, "replay differs for %s/%s" % (condition, item_id))
            report(
                identical == 36,
                "replay reproduces all 36 estimate records byte-identically "
                "(%d/36)" % identical,
            )
            out2 = os.path.join(tmp, "out2")
            replayed = subprocess.run(
                [
                    sys.executable,
                    EVALUATE,
                    "--run-dir",
                    run_dir,
                    "--output-dir",
                    out2,
                ],
                capture_output=True,
                text=True,
                env=scrub_env(),
            )
            report(
                replayed.returncode == 0,
                "evaluate.py runs without the model environment",
            )
            if replayed.returncode == 0:
                report(
                    read_bytes(os.path.join(out1, "results.json"))
                    == read_bytes(os.path.join(out2, "results.json"))
                    and read_bytes(os.path.join(out1, "verdict.md"))
                    == read_bytes(os.path.join(out2, "verdict.md")),
                    "replaying the run directory reproduces the verdict files "
                    "byte-identically",
                )
    finally:
        shutil.rmtree(tmp)

    print()
    if failures:
        print("%d check(s) failed" % len(failures))
        sys.exit(1)
    print("all evaluation checks passed")


if __name__ == "__main__":
    main()
