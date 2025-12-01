"""Generate the fixed-seed synthetic sprint history for the estimation experiment.

Writes the four record shapes (work item, estimate, outcome, evidence) and the
held-out Sprint 9 backlog plus its actuals under fixtures/. Reruns are
byte-identical. The planted ground-truth rules and record shapes are described
in contract.md.
"""

import argparse
import json
import os
import random

SEED = 20260928

POINTS = (1, 2, 3, 5, 8, 13)
CONFIDENCE_LEVELS = ("low", "medium", "high")

FACTORS = (
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
NEUTRAL_FACTORS = FACTORS[3:]

# Planted ground-truth multipliers. Items tagged with one of these factors get
# that rule; every other item gets the neutral rule. An item carries at most
# one planted factor so the rules never conflict.
PLANTED = {
    "migration": {"multiplier": 2.0, "noise": 0.1},
    "familiar-application": {"multiplier": 0.7, "noise": 0.1},
    "external-dependency": {"multiplier": 1.3, "noise": 0.6},
}
NEUTRAL_RULE = {"multiplier": 1.0, "noise": 0.2}

# Designed estimate sequences for the planted factors. Noise is taken from an
# evenly spaced grid across each factor's bound, and the sequence is chosen so
# the recorded per-factor median of actual/estimate recovers the planted
# multiplier after snapping to the point vocabulary (see contract.md).
COMPLETED_PLANTED_ESTIMATES = {
    "migration": [2, 3, 5, 1, 1, 2, 2],
    "familiar-application": [3, 3, 3, 3, 5, 8],
    "external-dependency": [3, 5, 3, 5, 5, 8],
}
HELD_OUT_PLANTED_ESTIMATES = {
    "migration": [2, 3, 5],
    "familiar-application": [3, 5, 8],
    "external-dependency": [3, 5, 8],
}
# Neutral items use the same grid mechanism. With the neutral bound of ±0.2
# only the two most-negative grid slots snap below the estimate, so the first
# two estimates are placed there (an 8 landing on 5 and a 3 landing on 2); all
# other neutral actuals snap back to the estimate and record ratio 1.0.
NEUTRAL_ESTIMATES = [8, 3, 3, 5, 2, 5, 8, 3, 2, 5, 3, 2, 8, 5, 3, 2, 5, 3, 2, 5, 8]
HELD_OUT_NEUTRAL_ESTIMATES = [3, 5, 8]
COMPLETED_SPRINTS = 8
HELD_OUT_SPRINT = 9
ITEMS_PER_SPRINT = 5

CONFIDENCE_BY_FACTOR = {
    "migration": "medium",
    "familiar-application": "high",
    "external-dependency": "low",
}

FACTOR_REASONS = {
    "migration": "historical migrations have exceeded base estimates",
    "familiar-application": "routine change on well-known code",
    "external-dependency": "third-party behaviour is outside the team's control",
    "novelty": "no comparable prior work to lean on",
    "ambiguity": "requirements are still contested",
    "unfamiliar-subsystem": "little team knowledge of this area",
    "cross-team": "work spans another team's ownership",
    "testing-burden": "large test surface relative to the change",
    "operational-risk": "mistakes in this path are expensive",
}

NOTES_BY_FACTOR = {
    "migration": ["similar migration work has historically exceeded base estimates"],
    "familiar-application": ["implementation is small and the code is well known"],
    "external-dependency": ["schedule risk sits mostly with the provider"],
}
GENERIC_NOTES = [
    "implementation appears small; uncertainty is in the integration",
    "confidence reflects how settled the requirements are",
    "estimate follows the historical pattern for this kind of work",
]

SUMMARIES = {
    "migration": [
        "Migrate billing export jobs off the legacy scheduler",
        "Move the customer import pipeline to the new data platform",
        "Rebuild the search index on the current stack and retire the old one",
    ],
    "familiar-application": [
        "Add a column set to the admin dashboard",
        "Extend the report export with an optional date range",
        "Fix the account settings page layout on narrow screens",
    ],
    "external-dependency": [
        "Integrate the payments provider webhooks",
        "Adopt the new geocoding service for address lookups",
        "Connect the order notification service",
    ],
    "novelty": [
        "Prototype the session replay recorder",
        "Explore the streaming ingestion path for analytics events",
    ],
    "ambiguity": [
        "Clarify the refund rules in the checkout flow",
        "Resolve the conflicting requirements for the search ranking",
    ],
    "unfamiliar-subsystem": [
        "Fix the flaky session store cleanup",
        "Extend the permission checks in the reporting service",
    ],
    "cross-team": [
        "Coordinate the shared schema change with the platform team",
        "Align the API deprecation timeline with the mobile team",
    ],
    "testing-burden": [
        "Expand the integration suite for the order lifecycle",
        "Cover the pricing edge cases with a property-based suite",
    ],
    "operational-risk": [
        "Change the retry policy on the payment retry worker",
        "Update the deployment script for the frontend bundle",
    ],
}

SENTENCES = {
    "migration": [
        "The existing jobs run on the legacy scheduler and are removed only after the replacement runs cleanly for a week.",
        "The new pipeline reads the same source tables and produces byte-compatible output files.",
        "Several downstream consumers read the current output format and are switched after the cutover.",
        "Historical data is replayed into the new system before the switch.",
        "The migration runs as a series of small cutovers to keep rollback cheap.",
    ],
    "familiar-application": [
        "The dashboard code follows the established widget pattern and is well understood.",
        "The change reuses the existing table component and only adds new columns.",
        "No new dependencies or services are involved.",
        "The export path already supports filters; only the UI and one query change.",
        "The settings page uses the shared form styles with minor overrides.",
    ],
    "external-dependency": [
        "The provider sandbox is available but the rate limits are not fully documented.",
        "Webhook payloads must be verified against the provider signing scheme.",
        "The geocoding API has known quirks around ambiguous addresses.",
        "The notification service may change its payload shape between releases.",
        "Failures must degrade gracefully while the provider is unreachable.",
    ],
    "novelty": [
        "No comparable feature exists in the codebase yet.",
        "The approach is uncertain and the first version is expected to be thrown away.",
        "The prototype only needs to work for the demo dataset.",
        "The team has not used this library before.",
        "Findings matter more than the implementation quality.",
    ],
    "ambiguity": [
        "Stakeholders disagree about the expected behaviour in edge cases.",
        "The ticket has been rewritten twice and may still change.",
        "The scope depends on a product decision that has not landed yet.",
        "The implementation is deferred until the decision is recorded.",
        "Only the agreed subset ships this sprint.",
    ],
    "unfamiliar-subsystem": [
        "The session store predates the current team and has no maintainer notes.",
        "The reporting service has grown a custom permission layer nobody fully understands.",
        "Behaviour is pinned with tests before changes are made.",
        "The change is kept small because the blast radius is unclear.",
        "Investigation time is included in the estimate.",
    ],
    "cross-team": [
        "The change touches a schema owned by another team.",
        "The rollout must line up with the mobile release train.",
        "Reviews from two other teams are required before merge.",
        "Part of the work is waiting on another team's availability.",
        "The deprecation notice needs a published date both teams accept.",
    ],
    "testing-burden": [
        "The change is small but the test surface is large.",
        "Existing coverage is thin, so tests are written first.",
        "The suite must run against a seeded database with fixed timestamps.",
        "Most of the effort goes into fixtures and test data.",
        "The tests also pin behaviour that has no specification.",
    ],
    "operational-risk": [
        "The worker runs unattended and a mistake could retry payments.",
        "The change needs a canary rollout and a fast rollback path.",
        "The deployment script is exercised against the staging environment first.",
        "Observability is added before the behaviour changes.",
        "The rollout window is coordinated with the support rotation.",
    ],
}

ACCEPTANCE = {
    "migration": [
        "Replacement job produces identical output for a seeded week of history",
        "Old jobs are disabled only after the new job passes monitoring checks",
        "Rollback procedure is documented and exercised once",
        "No gap or duplication in processed records across the cutover",
    ],
    "familiar-application": [
        "New columns render with the existing sort and filter behaviour",
        "Export respects the selected range on empty and boundary values",
        "Page passes the existing visual regression checks",
        "No changes to the public API surface",
    ],
    "external-dependency": [
        "Webhooks verify signatures and ignore unknown event types",
        "Provider outage degrades to queued retries without data loss",
        "Rate-limit responses back off and retry",
        "Sandbox end-to-end flow passes",
    ],
    "novelty": [
        "Prototype records and replays a session from the demo dataset",
        "Findings are written up with a recommendation",
        "No production traffic is touched",
        "Demo runs on the seeded dataset without manual steps",
    ],
    "ambiguity": [
        "Decision is recorded with the chosen edge-case behaviour",
        "Implementation follows the recorded decision",
        "Conflicting requirement is closed with the product owner",
        "Open questions are captured with owners",
    ],
    "unfamiliar-subsystem": [
        "Cleanup job runs without losing live sessions",
        "Permission changes are covered by new tests for each rule",
        "Known gaps are listed rather than fixed",
        "Regression tests pass on the seeded dataset",
    ],
    "cross-team": [
        "Schema change ships in the jointly agreed window",
        "Deprecation notice is posted and acknowledged",
        "No consumer breaks in the release following the change",
        "Both teams approve before merge",
    ],
    "testing-burden": [
        "Integration suite covers the full order lifecycle",
        "Edge-case fixtures are committed and deterministic",
        "Coverage of the changed paths is reported and reviewed",
        "Suite runtime stays under the build budget",
    ],
    "operational-risk": [
        "Canary rollout shows no increase in retry errors",
        "Rollback is verified in staging before the change ships",
        "New alerts fire on the failure modes the change could cause",
        "Runbook is updated for the new behaviour",
    ],
}

# (factor, index within the factor group) -> reason. Five overrides keep the
# override rate measurable within the required 4-6 band.
OVERRIDE_REASONS = {
    ("migration", 0): "underestimated the amount of cleanup the cutover required",
    ("migration", 5): "missed the backward-compatibility surface",
    ("familiar-application", 4): "the estimate assumed more surface area than the change touched",
    ("external-dependency", 0): "the provider sandbox behaved differently than documented",
    ("external-dependency", 3): "undocumented rate limits forced a redesign of the sync loop",
}

SURPRISES = {
    ("migration", 5): [
        {"kind": "scope-change", "detail": "backward-compatibility shim added mid-sprint"}
    ],
    ("familiar-application", 2): [
        {"kind": "new-dependency", "detail": "a shared library already covered the needed auth flow"}
    ],
    ("familiar-application", 4): [
        {"kind": "scope-change", "detail": "scope trimmed after design review"}
    ],
    ("external-dependency", 3): [
        {"kind": "new-dependency", "detail": "provider added an undocumented rate limit"}
    ],
    ("external-dependency", 4): [
        {"kind": "new-dependency", "detail": "webhook retry behaviour required an extra queue"}
    ],
    ("external-dependency", 5): [
        {"kind": "new-dependency", "detail": "payload schema changed between sandbox and production"}
    ],
}

HELD_OUT_SURPRISES = {
    ("external-dependency", 2): [
        {"kind": "new-dependency", "detail": "provider sandbox and production differ on retry behaviour"}
    ],
}


def _grid_noise(n, bound):
    return [bound * (2 * k + 1 - n) / n for k in range(n)]


def _snap(value):
    best = POINTS[0]
    for point in POINTS:
        if abs(value - point) <= abs(value - best):
            best = point
    return best


def _actual_points(estimate, rule, noise):
    return _snap(estimate * (rule["multiplier"] + noise))


def _interleave(groups):
    merged = []
    for k in range(max(len(group) for group in groups)):
        for group in groups:
            if k < len(group):
                merged.append(group[k])
    return merged


def _dump(payload, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _design(planted_estimates, neutral_estimates):
    planted_groups = []
    for factor, estimates in planted_estimates.items():
        noises = _grid_noise(len(estimates), PLANTED[factor]["noise"])
        planted_groups.append(
            [
                (factor, estimate, noise, k)
                for k, (estimate, noise) in enumerate(zip(estimates, noises))
            ]
        )
    planted = _interleave(planted_groups)
    neutral_noises = _grid_noise(len(neutral_estimates), NEUTRAL_RULE["noise"])
    neutral = [
        (None, estimate, noise, 0)
        for estimate, noise in zip(neutral_estimates, neutral_noises)
    ]
    merged = _interleave([planted, neutral[: len(planted)]])
    return merged + neutral[len(planted):]


def _content(rng, pool_key, index):
    summary = SUMMARIES[pool_key][index % len(SUMMARIES[pool_key])]
    description = " ".join(
        rng.sample(SENTENCES[pool_key], 2 + rng.randint(0, 2))
    )
    criteria = rng.sample(ACCEPTANCE[pool_key], 2 + rng.randint(0, 2))
    return summary, description, criteria


def _build(rng, design, sprint_of, first_id, reference_ids=None,
           overrides=None, surprises=None):
    items, estimates, outcomes, evidence = [], [], [], []
    group_ids = {}
    for index, (factor, estimate_points, noise, group_k) in enumerate(design):
        item_id = "SYN-%d" % (first_id + index)
        if factor is not None:
            tags = [factor] + rng.sample(NEUTRAL_FACTORS, rng.randint(0, 2))
        else:
            tags = rng.sample(NEUTRAL_FACTORS, rng.randint(1, 3))
        summary, description, criteria = _content(
            rng, factor or tags[0], group_k if factor is not None else index
        )
        items.append(
            {
                "item_id": item_id,
                "sprint": sprint_of(index),
                "summary": summary,
                "description": description,
                "acceptance_criteria": criteria,
            }
        )

        estimate = {
            "item_id": item_id,
            "points": estimate_points,
            "confidence": (
                CONFIDENCE_BY_FACTOR[factor]
                if factor in CONFIDENCE_BY_FACTOR
                else rng.choice(["medium", "high"])
            ),
            "factors": [{"tag": tag, "reason": FACTOR_REASONS[tag]} for tag in tags],
            "notes": rng.choice(NOTES_BY_FACTOR.get(factor, GENERIC_NOTES)),
        }
        if factor is not None:
            if reference_ids is not None:
                estimate["analogues"] = reference_ids[factor][:1]
            elif group_k >= 2:
                estimate["analogues"] = group_ids[factor][:2]
        estimates.append(estimate)
        group_ids.setdefault(factor, []).append(item_id)

        actual = _actual_points(
            estimate_points, PLANTED.get(factor, NEUTRAL_RULE), noise
        )
        outcome = {
            "item_id": item_id,
            "actual_points": actual,
            "engineering_days": round(actual * 0.5 * rng.uniform(0.8, 1.2), 1),
            "elapsed_days": 0.0,
        }
        outcome["elapsed_days"] = round(
            outcome["engineering_days"] + rng.uniform(0.0, 5.0), 1
        )
        if overrides and (factor, group_k) in overrides:
            outcome["override"] = {
                "reason": overrides[(factor, group_k)],
                "corrected_estimate": actual,
            }
        if surprises and (factor, group_k) in surprises:
            outcome["surprises"] = surprises[(factor, group_k)]
        outcomes.append(outcome)

        evidence.append(
            {
                "item_id": item_id,
                "work_item": items[-1],
                "estimate": estimates[-1],
                "outcome": outcomes[-1],
            }
        )
    return items, estimates, outcomes, evidence, group_ids


def write_fixtures(out_dir):
    rng = random.Random(SEED)
    completed_design = _design(COMPLETED_PLANTED_ESTIMATES, NEUTRAL_ESTIMATES)
    held_out_design = _design(HELD_OUT_PLANTED_ESTIMATES, HELD_OUT_NEUTRAL_ESTIMATES)

    items, estimates, outcomes, evidence, group_ids = _build(
        rng,
        completed_design,
        sprint_of=lambda i: 1 + i // ITEMS_PER_SPRINT,
        first_id=101,
        overrides=OVERRIDE_REASONS,
        surprises=SURPRISES,
    )
    held_items, held_estimates, held_outcomes, _, _ = _build(
        rng,
        held_out_design,
        sprint_of=lambda i: HELD_OUT_SPRINT,
        first_id=301,
        reference_ids=group_ids,
        surprises=HELD_OUT_SURPRISES,
    )

    _dump(items, os.path.join(out_dir, "work-items.json"))
    _dump(estimates, os.path.join(out_dir, "estimates.json"))
    _dump(outcomes, os.path.join(out_dir, "outcomes.json"))
    _dump(evidence, os.path.join(out_dir, "evidence.json"))
    _dump(
        {"items": held_items, "estimates": held_estimates},
        os.path.join(out_dir, "held-out", "backlog.json"),
    )
    _dump(
        held_outcomes,
        os.path.join(out_dir, "held-out", "held-out-actuals.json"),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate the fixed-seed synthetic sprint history fixtures."
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"),
        help="directory to write the fixture files into (default: fixtures/)",
    )
    args = parser.parse_args()
    write_fixtures(args.output)


if __name__ == "__main__":
    main()
