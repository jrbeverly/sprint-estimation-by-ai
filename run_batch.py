"""Run the three estimation conditions over the held-out backlog.

Reads fixtures/held-out/backlog.json and records one call per condition and
item pair into the run directory: unguided (no guidance), guided (the
guidance artifact), and history (the completed evidence records pasted into
the prompt). Requires the same environment as estimate.py for live runs;
--replay answers from the recorded run directory.
"""

import argparse
import json
import os

import estimate

ROOT = os.path.dirname(os.path.abspath(__file__))
CONDITIONS = (
    ("unguided", None),
    ("guided", os.path.join(ROOT, "guidance.txt")),
    ("history", os.path.join(ROOT, "fixtures", "evidence.json")),
)


def main():
    parser = argparse.ArgumentParser(
        description="Record one estimate call per condition and held-out "
        "item pair."
    )
    parser.add_argument(
        "--run-dir", required=True, help="directory that records the calls"
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="answer from the recorded responses; no model, no network",
    )
    args = parser.parse_args()
    with open(os.path.join(ROOT, "fixtures", "held-out", "backlog.json")) as handle:
        backlog = json.load(handle)
    counts = {}
    for condition, path in CONDITIONS:
        guidance = None
        if path:
            with open(path) as handle:
                guidance = handle.read()
        for item in backlog["items"]:
            estimate.estimate(item, guidance, condition, args.run_dir, args.replay)
            counts[condition] = counts.get(condition, 0) + 1
    print(
        "recorded %d calls: %s"
        % (
            sum(counts.values()),
            ", ".join(
                "%s=%d" % (condition, counts[condition])
                for condition, _ in CONDITIONS
            ),
        )
    )


if __name__ == "__main__":
    main()
