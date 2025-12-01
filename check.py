"""Validate the fixture set against the acceptance criteria of the
evidence-model issue: determinism, join integrity, planted-median recovery,
held-out containment, and record vocabulary.
"""

import ast
import json
import os
import shutil
import sys
import tempfile

import generate

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(ROOT, "fixtures")
HELD_OUT_ACTUALS_NAME = "held-out-actuals.json"

failures = []


def report(ok, message):
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        failures.append(message)


def load(path):
    with open(path) as handle:
        return json.load(handle)


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def relative_files(directory):
    found = []
    for dirpath, _, names in os.walk(directory):
        for name in names:
            full = os.path.join(dirpath, name)
            found.append(os.path.relpath(full, directory))
    return sorted(found)


def walk_json(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def main():
    # Criterion 1: running the generator twice produces byte-identical files.
    tmp = tempfile.mkdtemp(prefix="sprint-estimation-check-")
    try:
        generate.write_fixtures(os.path.join(tmp, "a"))
        generate.write_fixtures(os.path.join(tmp, "b"))
        paths_a = relative_files(os.path.join(tmp, "a"))
        paths_b = relative_files(os.path.join(tmp, "b"))
        committed = relative_files(FIXTURES)
        report(
            paths_a == paths_b == committed,
            "generator reruns and the committed copy have the same file set",
        )
        identical = True
        for rel in paths_a:
            with open(os.path.join(tmp, "a", rel), "rb") as handle:
                first = handle.read()
            with open(os.path.join(tmp, "b", rel), "rb") as handle:
                second = handle.read()
            with open(os.path.join(FIXTURES, rel), "rb") as handle:
                committed_bytes = handle.read()
            if first != second or first != committed_bytes:
                identical = False
                report(False, "byte-identical fixture: %s" % rel)
        if identical:
            report(
                True,
                "two generator runs and the committed fixtures are byte-identical",
            )
    finally:
        shutil.rmtree(tmp)

    items = load(os.path.join(FIXTURES, "work-items.json"))
    estimates = load(os.path.join(FIXTURES, "estimates.json"))
    outcomes = load(os.path.join(FIXTURES, "outcomes.json"))
    evidence = load(os.path.join(FIXTURES, "evidence.json"))
    backlog = load(os.path.join(FIXTURES, "held-out", "backlog.json"))
    held_items = backlog["items"]
    held_estimates = backlog["estimates"]
    held_actuals = load(
        os.path.join(FIXTURES, "held-out", HELD_OUT_ACTUALS_NAME)
    )

    # Criterion 2: join integrity, no orphans, no duplicates.
    report(
        len(items) == 40
        and len(estimates) == 40
        and len(outcomes) == 40
        and len(evidence) == 40,
        "40 completed work items, estimates, outcomes, and evidence records",
    )
    item_ids = {record["item_id"] for record in items}
    estimate_ids = {record["item_id"] for record in estimates}
    outcome_ids = {record["item_id"] for record in outcomes}
    evidence_ids = {record["item_id"] for record in evidence}
    report(
        item_ids == estimate_ids == outcome_ids == evidence_ids
        and len(item_ids) == 40,
        "every evidence record joins its item, estimate, and outcome by id "
        "(no orphans, no duplicates)",
    )
    items_by_id = {record["item_id"]: record for record in items}
    estimates_by_id = {record["item_id"]: record for record in estimates}
    outcomes_by_id = {record["item_id"]: record for record in outcomes}
    report(
        all(
            record["work_item"] == items_by_id[record["item_id"]]
            and record["estimate"] == estimates_by_id[record["item_id"]]
            and record["outcome"] == outcomes_by_id[record["item_id"]]
            for record in evidence
        ),
        "each evidence record embeds exactly its standalone item, estimate, "
        "and outcome",
    )
    sprints = sorted({record["sprint"] for record in items})
    report(
        sprints == list(range(1, 9))
        and all(
            len([r for r in items if r["sprint"] == s]) == 5 for s in sprints
        ),
        "8 completed sprints with 5 items each",
    )

    # Held-out backlog.
    report(
        len(held_items) == 12
        and len(held_estimates) == 12
        and len(held_actuals) == 12,
        "held-out backlog: 12 items, 12 estimates, 12 actuals",
    )
    report(
        all(record["sprint"] == 9 for record in held_items),
        "held-out items are all sprint 9",
    )
    report(
        {r["item_id"] for r in held_actuals} == {r["item_id"] for r in held_items},
        "every held-out item has exactly one actuals record",
    )

    # Record vocabulary.
    report(
        all(record["points"] in generate.POINTS for record in estimates)
        and all(
            record["actual_points"] in generate.POINTS
            for record in outcomes + held_actuals
        ),
        "all points and actuals use the fixed vocabulary",
    )
    report(
        all(
            record["confidence"] in generate.CONFIDENCE_LEVELS
            for record in estimates + held_estimates
        ),
        "confidence levels stay in vocabulary",
    )
    report(
        all(
            factor["tag"] in generate.FACTORS and factor["reason"]
            for record in estimates + held_estimates
            for factor in record["factors"]
        )
        and all(record["factors"] for record in estimates + held_estimates),
        "factor tags stay in the nine-factor vocabulary with a reason each",
    )

    # Overrides: 4-6 outcomes, each with reason and corrected estimate.
    overrides = [record for record in outcomes if "override" in record]
    report(
        4 <= len(overrides) <= 6,
        "%d outcomes carry an override (expected 4-6)" % len(overrides),
    )
    report(
        all(
            record["override"]["reason"]
            and record["override"]["corrected_estimate"] in generate.POINTS
            for record in overrides
        ),
        "each override carries a reason and a vocabulary corrected estimate",
    )

    # Criteria 3 and 4: planted-factor minimums and median recovery.
    ratios_by_factor = {factor: [] for factor in generate.PLANTED}
    for record in evidence:
        estimate = record["estimate"]
        actual = record["outcome"]["actual_points"]
        for factor in estimate["factors"]:
            tag = factor["tag"]
            if tag in generate.PLANTED:
                ratios_by_factor[tag].append(actual / estimate["points"])
    print("per-factor median actual/estimate over the completed fixtures:")
    for factor, planted in generate.PLANTED.items():
        ratios = ratios_by_factor[factor]
        med = median(ratios)
        distance = abs(med - planted["multiplier"])
        report(
            len(ratios) >= 6 and distance <= 0.1,
            "  %-22s n=%d median=%.4g planted=%.1f (distance %.4g)"
            % (factor, len(ratios), med, planted["multiplier"], distance),
        )
    held_by_factor = {factor: set() for factor in generate.PLANTED}
    for record in held_estimates:
        for factor in record["factors"]:
            if factor["tag"] in generate.PLANTED:
                held_by_factor[factor["tag"]].add(record["item_id"])
    report(
        all(len(ids) >= 3 for ids in held_by_factor.values()),
        "held-out backlog has at least 3 items per planted factor (%s)"
        % ", ".join(
            "%s=%d" % (factor, len(ids))
            for factor, ids in held_by_factor.items()
        ),
    )
    neutral_ratios = []
    for record in evidence:
        tags = [factor["tag"] for factor in record["estimate"]["factors"]]
        if not set(tags) & set(generate.PLANTED):
            neutral_ratios.append(
                record["outcome"]["actual_points"] / record["estimate"]["points"]
            )
    print(
        "info: neutral items median actual/estimate = %.4g (planted 1.0)"
        % median(neutral_ratios)
    )

    # Criterion 5: held-out actuals in exactly one committed file.
    held_out_ids = {record["item_id"] for record in held_actuals}
    name_matches = [
        os.path.join(dirpath, name)
        for dirpath, _, names in os.walk(ROOT)
        for name in names
        if name == HELD_OUT_ACTUALS_NAME
    ]
    report(
        name_matches
        == [os.path.join(FIXTURES, "held-out", HELD_OUT_ACTUALS_NAME)],
        "exactly one %s file, at fixtures/held-out/" % HELD_OUT_ACTUALS_NAME,
    )
    allowed_ids_files = {
        os.path.abspath(os.path.join(FIXTURES, "held-out", HELD_OUT_ACTUALS_NAME)),
        os.path.abspath(os.path.join(FIXTURES, "held-out", "backlog.json")),
    }
    id_leaks = []
    for dirpath, _, names in os.walk(ROOT):
        for name in names:
            path = os.path.abspath(os.path.join(dirpath, name))
            if path in allowed_ids_files:
                continue
            with open(path, errors="replace") as handle:
                text = handle.read()
            hits = sorted(i for i in held_out_ids if i in text)
            if hits:
                id_leaks.append(
                    "%s: %s" % (os.path.relpath(path, ROOT), hits)
                )
    report(
        not id_leaks,
        "held-out ids appear only in the held-out files",
    )
    for leak in id_leaks:
        print("      leaked: %s" % leak)
    actual_leaks = []
    for dirpath, _, names in os.walk(FIXTURES):
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.abspath(os.path.join(dirpath, name))
            data = load(path)
            for record in walk_json(data):
                if (
                    isinstance(record, dict)
                    and record.get("item_id") in held_out_ids
                    and "actual_points" in record
                    and path
                    != os.path.abspath(
                        os.path.join(FIXTURES, "held-out", HELD_OUT_ACTUALS_NAME)
                    )
                ):
                    actual_leaks.append(os.path.relpath(path, FIXTURES))
    report(
        not actual_leaks,
        "no other JSON file under the experiment records held-out actuals",
    )

    # Criterion 6: standard library only, no network-capable imports.
    banned_modules = {"requests", "urllib", "http", "socket", "ftplib", "jira", "acli"}
    for script in ("generate.py", "check.py"):
        with open(os.path.join(ROOT, script)) as handle:
            tree = ast.parse(handle.read())
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                used.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                used.add(node.module.split(".")[0])
        found = sorted(used & banned_modules)
        report(
            not found,
            "%s uses only the standard library" % script,
        )

    # Criterion 7: no credential-shaped content in the fixture data.
    banned_words = ("password", "api_key", "apikey", "secret", "credential")
    word_hits = []
    for dirpath, _, names in os.walk(FIXTURES):
        for name in names:
            if not name.endswith(".json"):
                continue
            with open(os.path.join(dirpath, name), errors="replace") as handle:
                text = handle.read().lower()
            found = [word for word in banned_words if word in text]
            if found:
                word_hits.append((name, found))
    report(
        not word_hits,
        "no credential-shaped words in the fixture data",
    )
    for name, found in word_hits:
        print("      %s: %s" % (name, found))

    print()
    print(
        "counts: %d items, %d estimates, %d outcomes, %d evidence records, "
        "%d overrides; held-out %d items / %d actuals"
        % (
            len(items),
            len(estimates),
            len(outcomes),
            len(evidence),
            len(overrides),
            len(held_items),
            len(held_actuals),
        )
    )
    if failures:
        print("%d check(s) failed" % len(failures))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
