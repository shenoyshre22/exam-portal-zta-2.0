"""
Centralized route -> role authorization policy for SentinelGate.

This is what turns the gateway from a blind proxy (B9/B10 in the audit) into a
Policy Enforcement Point: every protected route is evaluated here, once, before
the request is forwarded anywhere. Downstream services keep their own checks as
defense-in-depth, but this table is now the single source of truth.

The policy itself lives in policy_config.json, not in this file — operators can
add a route, change a role, or add an ownership check without touching gateway
code or redeploying the image (only a container restart to reload the file).
"""

import json
import os
from fastapi import HTTPException

_CONFIG_PATH = os.getenv(
    "SENTINELGATE_POLICY_CONFIG",
    os.path.join(os.path.dirname(__file__), "policy_config.json"),
)

# Fallback used only if policy_config.json is missing (e.g. a stripped-down local
# run) so the gateway fails closed to something sane rather than crashing.
_FALLBACK_POLICY = {
    "POST /questions/add-mcq": ["teacher"],
    "POST /questions/upload-pdf": ["teacher"],
    "POST /exams": ["teacher"],
    "POST /evaluate": ["teacher"],
    "GET /evaluations/{student_id}": ["teacher"],
    "POST /publish-result": ["teacher"],
    "POST /submit-answer": ["student"],
    "GET /logs": ["teacher"],
}
_FALLBACK_OWNERSHIP = {
    "GET /submissions/{student_id}": "student_id",
    "GET /results/{student_id}": "student_id",
    "GET /logs/{user_id}": "user_id",
}


def _load_policy_config(path: str):
    try:
        with open(path) as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Warning: could not load {path} ({exc}); using built-in fallback policy")
        raw = {"policy": _FALLBACK_POLICY, "ownership_params": _FALLBACK_OWNERSHIP}

    # JSON keys are "METHOD /route" strings; split back into the (method, route) tuples used below.
    policy = {}
    for key, roles in raw.get("policy", {}).items():
        method, route = key.split(" ", 1)
        policy[(method, route)] = set(roles)

    ownership = {}
    for key, param_name in raw.get("ownership_params", {}).items():
        method, route = key.split(" ", 1)
        ownership[(method, route)] = param_name

    return policy, ownership


POLICY, OWNERSHIP_PARAMS = _load_policy_config(_CONFIG_PATH)


def authorize(method: str, route_template: str, user: dict):
    """Raise 403 if this role isn't permitted for this route. Silent pass-through otherwise."""
    allowed = POLICY.get((method, route_template))
    if allowed is not None and user.get("role") not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.get('role')}' is not permitted to {method} {route_template}",
        )


def enforce_ownership(method: str, route_template: str, user: dict, **path_params):
    """Raise 403 if a student is requesting a resource that isn't theirs."""
    param_name = OWNERSHIP_PARAMS.get((method, route_template))
    if not param_name:
        return
    requested = path_params.get(param_name)
    if user.get("role") == "student" and user.get("username") != requested:
        raise HTTPException(status_code=403, detail="You can only access your own resource")


def filter_question_fields(data, role: str):
    """Strip the answer key from question payloads for non-teacher roles (fixes B5)."""
    if role == "teacher":
        return data
    if isinstance(data, list):
        return [_strip_answer(q) for q in data]
    return _strip_answer(data)


def _strip_answer(q):
    if isinstance(q, dict):
        return {k: v for k, v in q.items() if k != "correct_answer"}
    return q

