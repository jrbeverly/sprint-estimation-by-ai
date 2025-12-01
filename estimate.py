"""Estimate one work item with a recorded model call.

Turns a work-item file (plus an optional guidance artifact) into an estimate
record in the shape defined by contract.md. Model selection and credentials
come from the environment only: ANTHROPIC_MODEL, ANTHROPIC_BASE_URL, and
ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN. Every call's input (item, guidance,
prompt) and raw response are written to the run directory, so the run replays
with --replay and no model, no network, and no secrets.
"""

import argparse
import json
import os
import sys

import generate

PROMPT_HEADER = (
    "Estimate the work item below for sprint planning.\n"
    "Reply with exactly one JSON object and nothing else.\n"
    "\n"
    "points: one of 1, 2, 3, 5, 8, 13 (integers only)\n"
    "confidence: one of low, medium, high\n"
    "factors: one or more of the tags below that are present in the item "
    "text itself, each with a one-line reason\n"
    "  migration - replacing or moving existing functionality off a legacy system\n"
    "  familiar-application - routine change on code the team knows well\n"
    "  external-dependency - relies on a third-party service or provider\n"
    "  novelty - no comparable prior work in the codebase\n"
    "  ambiguity - requirements or scope still unsettled\n"
    "  unfamiliar-subsystem - touches an area the team has little knowledge of\n"
    "  cross-team - spans another team's ownership or schedule\n"
    "  testing-burden - large test surface relative to the change\n"
    "  operational-risk - mistakes in this path are expensive\n"
    "notes: one or two sentences explaining the estimate\n"
    'Required shape: {"item_id": "<item id>", "points": <int>, '
    '"confidence": "<low|medium|high>", "factors": [{"tag": "<tag>", '
    '"reason": "<one line>"}], "notes": "<text>", "analogues": ["<earlier '
    'item id>"]}\n'
    'Include "analogues" only when citing comparable earlier items.\n'
)

NO_MODEL_MESSAGE = (
    "no model available and no recorded response: set ANTHROPIC_MODEL, "
    "ANTHROPIC_BASE_URL, and ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN, "
    "or record the call first"
)


def build_prompt(item, guidance):
    sections = [PROMPT_HEADER]
    if guidance:
        sections.append("Guidance:\n" + guidance)
    sections.append("Work item:\n" + json.dumps(item, indent=2, sort_keys=True))
    return "\n".join(sections)


def extract_text(raw):
    try:
        message = json.loads(raw)
    except ValueError:
        raise ValueError("model response is not JSON")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        raise ValueError("unexpected model response shape")
    if message.get("stop_reason") != "end_turn":
        raise ValueError("model did not finish (stop_reason %r)" % message.get("stop_reason"))
    parts = [
        block["text"]
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    ]
    if not parts:
        raise ValueError("no text in the model response")
    return "\n".join(parts)


def parse_estimate(raw, item_id):
    text = extract_text(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the model response")
    try:
        record = json.loads(text[start : end + 1])
    except ValueError:
        raise ValueError("the model's JSON object does not parse")
    if not isinstance(record, dict):
        raise ValueError("the model's JSON object is not a record")
    problems = []
    if record.get("item_id") != item_id:
        problems.append("item_id does not match the work item")
    if (
        not isinstance(record.get("points"), int)
        or isinstance(record.get("points"), bool)
        or record.get("points") not in generate.POINTS
    ):
        problems.append("points outside the vocabulary")
    if record.get("confidence") not in generate.CONFIDENCE_LEVELS:
        problems.append("confidence not in low/medium/high")
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
                problems.append("factor tag outside the vocabulary or reason missing")
    if not isinstance(record.get("notes"), str) or not record["notes"].strip():
        problems.append("notes missing")
    if "analogues" in record and (
        not isinstance(record["analogues"], list)
        or not all(isinstance(analogue, str) for analogue in record["analogues"])
    ):
        problems.append("analogues malformed")
    if problems:
        raise ValueError("invalid estimate record: " + "; ".join(problems))
    return record


def call_model(model, endpoint, api_key, auth_token, prompt):
    """Single entry point for the model call; the rest of this module runs
    without touching the network."""
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = "Bearer " + auth_token
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 16384,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/messages", data=body, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read().decode()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(
            "model call failed with HTTP %d: %s" % (error.code, detail)
        )
    except urllib.error.URLError as error:
        raise SystemExit("model call failed: %s" % error.reason)


def model_from_env():
    model = os.environ.get("ANTHROPIC_MODEL")
    endpoint = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not (model and endpoint and (api_key or auth_token)):
        return None
    return {
        "model": model,
        "endpoint": endpoint,
        "api_key": api_key,
        "auth_token": auth_token,
    }


def call_dir(run_dir, condition, item_id):
    return os.path.join(run_dir, "calls", condition, item_id)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return json.load(handle)


def estimate(item, guidance, condition, run_dir, replay=False):
    if not isinstance(item, dict) or not isinstance(item.get("item_id"), str):
        raise SystemExit("the work item must be a record with an item_id")
    prompt = build_prompt(item, guidance)
    directory = call_dir(run_dir, condition, item["item_id"])
    request_path = os.path.join(directory, "request.json")
    estimate_path = os.path.join(directory, "estimate.json")
    env = None if replay else model_from_env()
    if env is None:
        recorded_request = load_json(request_path)
        recorded_estimate = load_json(estimate_path)
        if recorded_estimate is None:
            raise SystemExit(NO_MODEL_MESSAGE)
        if (
            recorded_request is None
            or recorded_request.get("item") != item
            or recorded_request.get("guidance") != guidance
            or recorded_request.get("condition") != condition
        ):
            raise SystemExit(
                "recorded call for %s/%s does not match this request"
                % (condition, item["item_id"])
            )
        return recorded_estimate
    if load_json(estimate_path) is not None:
        raise SystemExit(
            "a recorded call already exists for %s/%s; use --replay or a "
            "fresh run directory" % (condition, item["item_id"])
        )
    write_json(
        request_path,
        {
            "condition": condition,
            "model": env["model"],
            "endpoint": env["endpoint"],
            "item": item,
            "guidance": guidance,
            "prompt": prompt,
        },
    )
    raw = call_model(
        env["model"], env["endpoint"], env["api_key"], env["auth_token"], prompt
    )
    with open(os.path.join(directory, "response.json"), "w") as handle:
        handle.write(raw)
    record = parse_estimate(raw, item["item_id"])
    write_json(estimate_path, record)
    return record


def main():
    parser = argparse.ArgumentParser(
        description="Estimate one work item; every call is recorded and "
        "replays without the model."
    )
    parser.add_argument("--item", required=True, help="JSON file with one work item")
    parser.add_argument("--guidance", help="optional guidance artifact file")
    parser.add_argument(
        "--condition",
        default="unguided",
        help="condition name recorded with the call (default: unguided)",
    )
    parser.add_argument(
        "--run-dir", required=True, help="directory that records the calls"
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="answer from the recorded response; no model, no network",
    )
    args = parser.parse_args()
    with open(args.item) as handle:
        item = json.load(handle)
    guidance = None
    if args.guidance:
        with open(args.guidance) as handle:
            guidance = handle.read()
    record = estimate(item, guidance, args.condition, args.run_dir, args.replay)
    json.dump(record, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
