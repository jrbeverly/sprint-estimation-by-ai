"""Validate the estimator step against its acceptance criteria: the recorded
fixture, the 36-call three-condition run, byte-identical replay without the
model, record vocabulary, held-out-actuals isolation, and credential hygiene.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
RECORDED = os.path.join(ROOT, "recorded")
HELD_OUT_ACTUALS_NAME = "held-out-actuals.json"
ESTIMATOR_SOURCES = (
    os.path.join(ROOT, "estimate.py"),
    os.path.join(ROOT, "run_batch.py"),
)

failures = []


def report(ok, message):
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        failures.append(message)


def walk_json(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def validate_record(record):
    problems = []
    if not isinstance(record.get("points"), int) or isinstance(
        record.get("points"), bool
    ):
        problems.append("points is not an integer")
    elif record["points"] not in (1, 2, 3, 5, 8, 13):
        problems.append("points %r outside the vocabulary" % record["points"])
    if record.get("confidence") not in ("low", "medium", "high"):
        problems.append("confidence outside low/medium/high")
    factors = record.get("factors")
    if not isinstance(factors, list) or not factors:
        problems.append("no factors")
    else:
        for factor in factors:
            if (
                not isinstance(factor, dict)
                or factor.get("tag")
                not in (
                    "migration",
                    "familiar-application",
                    "external-dependency",
                    "novelty",
                    "ambiguity",
                    "unfamiliar-subsystem",
                    "cross-team",
                    "testing-burden",
                    "operational-risk",
                )
                or not isinstance(factor.get("reason"), str)
                or not factor["reason"].strip()
            ):
                problems.append("factor outside the vocabulary or reason missing")
    if not isinstance(record.get("notes"), str) or not record["notes"].strip():
        problems.append("notes missing")
    return problems


def scrubbed_env():
    env = dict(os.environ)
    for name in list(env):
        if name.startswith("ANTHROPIC"):
            del env[name]
    return env


def run_estimator(item_path, guidance_path, condition, run_dir, replay=True):
    command = [
        sys.executable,
        os.path.join(ROOT, "estimate.py"),
        "--item",
        item_path,
        "--condition",
        condition,
        "--run-dir",
        run_dir,
    ]
    if guidance_path:
        command += ["--guidance", guidance_path]
    if replay:
        command.append("--replay")
    result = subprocess.run(command, capture_output=True, text=True, env=scrubbed_env())
    if result.returncode != 0:
        report(
            False,
            "replay failed for %s/%s: %s" % (condition, run_dir, result.stderr.strip()),
        )
        return None
    return result.stdout


def recorded_calls(run_dir):
    calls = []
    root = os.path.join(run_dir, "calls")
    if not os.path.isdir(root):
        return calls
    for condition in sorted(os.listdir(root)):
        for item_id in sorted(os.listdir(os.path.join(root, condition))):
            calls.append((condition, item_id))
    return calls


def main():
    # Criterion 1: the committed recorded fixture replays to a valid record.
    report(
        os.path.isdir(RECORDED),
        "committed recorded fixture exists at recorded/",
    )
    fixture_calls = recorded_calls(RECORDED)
    report(
        len(fixture_calls) == 1,
        "the recorded fixture holds exactly one recorded call",
    )
    if fixture_calls:
        condition, item_id = fixture_calls[0]
        with open(os.path.join(RECORDED, "calls", condition, item_id, "request.json")) as handle:
            request = json.load(handle)
        with open(os.path.join(RECORDED, "item.json")) as handle:
            fixture_item = json.load(handle)
        output = run_estimator(
            os.path.join(RECORDED, "item.json"),
            None,
            condition,
            RECORDED,
        )
        if output is not None:
            record = json.loads(output)
            problems = validate_record(record)
            report(
                not problems,
                "fixture replay produces a valid estimate record (%s)"
                % ("; ".join(problems) if problems else "ok"),
            )
            with open(
                os.path.join(RECORDED, "calls", condition, item_id, "estimate.json")
            ) as handle:
                stored = handle.read()
            report(
                output == stored,
                "fixture replay is byte-identical to the recorded estimate",
            )
            report(
                record["item_id"] == fixture_item["item_id"],
                "fixture estimate joins the replayed work item",
            )
            report(
                request["item"] == fixture_item,
                "recorded request embeds the fixture item",
            )

    # Criterion 2: the three conditions over the held-out backlog record 36 calls.
    run_dir = tempfile.mkdtemp(prefix="sprint-estimation-run-")
    try:
        print("running the live batch (36 calls, may take a while)...")
        batch = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "run_batch.py"),
                "--run-dir",
                run_dir,
            ],
            capture_output=True,
            text=True,
        )
        detail = batch.stderr.strip()
        report(
            batch.returncode == 0,
            "live batch run succeeds%s"
            % (": " + detail[-200:] if detail else ""),
        )
        calls = recorded_calls(run_dir)
        report(
            len(calls) == 36,
            "36 recorded calls (12 items x 3 conditions), got %d" % len(calls),
        )
        per_condition = {}
        for condition, _ in calls:
            per_condition[condition] = per_condition.get(condition, 0) + 1
        report(
            per_condition
            == {"guided": 12, "history": 12, "unguided": 12},
            "12 calls per condition (%s)"
            % ", ".join("%s=%d" % item for item in sorted(per_condition.items())),
        )
        complete = []
        for condition, item_id in calls:
            directory = os.path.join(run_dir, "calls", condition, item_id)
            files = [
                name
                for name in ("request.json", "response.json", "estimate.json")
                if os.path.getsize(os.path.join(directory, name)) == 0
            ]
            if files:
                report(
                    False,
                    "empty recorded file(s) for %s/%s: %s"
                    % (condition, item_id, ", ".join(files)),
                )
            else:
                complete.append((condition, item_id))
        report(
            len(complete) == 36,
            "every recorded call has a request, response, and estimate",
        )

        # Criterion 3: replay with the model unavailable is byte-identical.
        print("replaying the run directory with the model unavailable...")
        identical = 0
        for condition, item_id in calls:
            directory = os.path.join(run_dir, "calls", condition, item_id)
            with open(os.path.join(directory, "request.json")) as handle:
                request = json.load(handle)
            item_path = os.path.join(run_dir, "replay-item.json")
            with open(item_path, "w") as handle:
                json.dump(request["item"], handle)
            guidance_path = None
            if request.get("guidance") is not None:
                guidance_path = os.path.join(run_dir, "replay-guidance.txt")
                with open(guidance_path, "w") as handle:
                    handle.write(request["guidance"])
            output = run_estimator(item_path, guidance_path, condition, run_dir)
            if output is None:
                continue
            with open(os.path.join(directory, "estimate.json")) as handle:
                stored = handle.read()
            if output == stored:
                identical += 1
            else:
                report(False, "replay differs for %s/%s" % (condition, item_id))
        report(
            identical == 36,
            "replay reproduces all 36 estimate records byte-identically (%d/36)"
            % identical,
        )

        # Criterion 4: every estimate record stays in the vocabulary.
        estimate_paths = []
        for directory in (run_dir, RECORDED):
            for dirpath, _, names in os.walk(directory):
                for name in names:
                    if name == "estimate.json":
                        estimate_paths.append(os.path.join(dirpath, name))
        bad = []
        for path in estimate_paths:
            label = os.path.relpath(path, run_dir)
            with open(path) as handle:
                record = json.load(handle)
            for node in walk_json(record):
                if isinstance(node, float):
                    bad.append((label, "fractional value %r" % node))
            bad.extend(
                (label, problem) for problem in validate_record(record)
            )
        report(
            not bad,
            "%d estimate records scanned, all values in the vocabulary"
            % len(estimate_paths),
        )
        for label, problem in bad:
            print("      %s: %s" % (label, problem))

        # Criterion 6: the run directories hold no credentials.
        credential_values = [
            value
            for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
            for value in [os.environ.get(name)]
            if value
        ]
        leaks = []
        header_names = ("Authorization", "x-api-key", "Bearer ")
        for directory in (run_dir, RECORDED):
            for dirpath, _, names in os.walk(directory):
                for name in names:
                    with open(
                        os.path.join(dirpath, name), errors="replace"
                    ) as handle:
                        text = handle.read()
                    label = os.path.join(os.path.relpath(dirpath, directory), name)
                    for value in credential_values:
                        if value in text:
                            leaks.append("%s: ambient credential value" % label)
                    for header in header_names:
                        if header in text:
                            leaks.append("%s: %r header" % (label, header))
        report(
            not leaks,
            "run directories contain no credentials or auth headers",
        )
        for leak in leaks:
            print("      %s" % leak)
    finally:
        shutil.rmtree(run_dir)

    # Criterion 5: the estimator source never references the held-out actuals file.
    for source in ESTIMATOR_SOURCES:
        with open(source) as handle:
            text = handle.read()
        report(
            HELD_OUT_ACTUALS_NAME not in text,
            "%s contains no reference to %s"
            % (os.path.basename(source), HELD_OUT_ACTUALS_NAME),
        )

    # Criterion 6: no committed model or endpoint defaults in the estimator source.
    for source in ESTIMATOR_SOURCES:
        with open(source) as handle:
            text = handle.read()
        report(
            "https://" not in text and re.search(r"environ\.get\([^)]*,", text) is None,
            "%s commits no model or endpoint defaults" % os.path.basename(source),
        )

    print()
    if failures:
        print("%d check(s) failed" % len(failures))
        sys.exit(1)
    print("all estimator checks passed")


if __name__ == "__main__":
    main()
