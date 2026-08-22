"""
feature_engineering.py

Offline feature engineering for SentinelGate's anomaly detection pipeline.

Reads the exported gateway telemetry (CSV, matching the `logs` table schema from
logging_service: id, user_id, service, event_type, description, timestamp) and
computes three per-request features, per user, using trailing time windows:

    req_count_5s   -- how many requests this user made in the last 5 seconds
                      (including the current one). Spikes here are the signature
                      of scripted/replayed traffic (e.g. rapid-fire IDOR probing).

    denied_ratio    -- fraction of this user's requests in the last `context_window`
                      seconds (default 60s) that the gateway BLOCKED. A legitimate
                      student almost never gets 403s; an attacker probing routes
                      they don't have permission for will show a high ratio.

    route_entropy   -- number of *distinct* gateway routes this user hit in the last
                      `context_window` seconds. A student taking one exam touches a
                      handful of routes in a session; lateral-movement / route-probing
                      traffic touches many.

No live scoring happens here and nothing runs inside the gateway's request path --
this is a pure offline, reproducible step: export -> this script -> DataFrame ->
scikit-learn IsolationForest. See CHANGES.md, "Scope lock" section, for why this
was chosen over in-memory live scoring.

Usage:
    python feature_engineering.py --input gateway_logs.csv --output features.csv
    python feature_engineering.py --input gateway_logs.csv --output features.csv \
        --attacker-users student1,student7 --attacker-services gateway
"""

import argparse
import math
import re
from bisect import bisect_left
from collections import defaultdict

import pandas as pd

# Matches gateway log descriptions produced by api_gateway/main.py's enforce():
#   ALLOWED  -> "GET /submissions/{student_id}"
#   BLOCKED  -> "GET /submissions/{student_id} -> Role 'student' is not permitted..."
DESCRIPTION_RE = re.compile(r"^(?P<method>[A-Z]+)\s+(?P<route>\S+)")


def load_gateway_events(csv_path: str) -> pd.DataFrame:
    """
    Load the exported log CSV and keep only gateway-emitted events.

    Only the gateway's own ALLOWED/BLOCKED events represent the full per-request
    stream at the enforcement point. Other services log business events (MCQ_ADDED,
    EVALUATION_STORED, etc.) that aren't part of this feature set.
    """
    df = pd.read_csv(csv_path)

    required = {"user_id", "service", "event_type", "description", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input CSV is missing expected columns: {sorted(missing)}")

    df = df[df["service"] == "gateway"].copy()
    df = df[df["event_type"].isin(["ALLOWED", "BLOCKED"])].copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce", format="mixed")
    before = len(df)
    df = df.dropna(subset=["timestamp"])
    if len(df) < before:
        print(f"Warning: dropped {before - len(df)} rows with unparseable timestamps")

    parsed = df["description"].astype(str).str.extract(DESCRIPTION_RE)
    df["method"] = parsed["method"]
    df["route"] = parsed["route"]
    unparsed = df["route"].isna().sum()
    if unparsed:
        print(f"Warning: {unparsed} rows had a description that didn't match the "
              f"expected 'METHOD /route' format and were dropped")
    df = df.dropna(subset=["route"])

    df["is_blocked"] = (df["event_type"] == "BLOCKED").astype(int)

    df = df.sort_values(["user_id", "timestamp"]).reset_index(drop=True)
    return df[["user_id", "timestamp", "method", "route", "is_blocked"]]


def compute_features(
    df: pd.DataFrame,
    count_window_s: float = 5.0,
    context_window_s: float = 60.0,
) -> pd.DataFrame:
    """
    Compute req_count_5s, denied_ratio, route_entropy for every event, per user,
    using a sliding time window (two-pointer, O(n) per user).

    Windows are trailing and inclusive of the current event: a request's own
    features describe "what this user's traffic looked like up to and including
    this moment," which is what a live gateway would have seen if it were scoring
    in real time -- we're just computing it after the fact, offline.
    """
    feature_rows = []

    for user_id, group in df.groupby("user_id", sort=False):
        timestamps = group["timestamp"].tolist()
        routes = group["route"].tolist()
        blocked = group["is_blocked"].tolist()
        epoch = [ts.timestamp() for ts in timestamps]

        left_count = 0   # window start index for the count_window (5s)
        left_ctx = 0      # window start index for the context_window (60s)

        for i in range(len(epoch)):
            now = epoch[i]

            while epoch[left_count] < now - count_window_s:
                left_count += 1
            req_count = i - left_count + 1

            while epoch[left_ctx] < now - context_window_s:
                left_ctx += 1
            window_routes = routes[left_ctx:i + 1]
            window_blocked = blocked[left_ctx:i + 1]

            window_size = len(window_blocked)
            denied_ratio = sum(window_blocked) / window_size if window_size else 0.0
            route_entropy = len(set(window_routes))

            feature_rows.append({
                "user_id": user_id,
                "timestamp": timestamps[i],
                "method": group["method"].iloc[i],
                "route": routes[i],
                "is_blocked": blocked[i],
                "req_count_5s": req_count,
                "denied_ratio": round(denied_ratio, 4),
                "route_entropy": route_entropy,
            })

    result = pd.DataFrame(feature_rows)
    return result.sort_values(["timestamp"]).reset_index(drop=True)


def shannon_route_entropy(routes: list) -> float:
    """
    Optional, more rigorous alternative to the plain distinct-route count above.
    Not used by default -- swap in via --true-entropy if a reviewer wants a
    proper information-theoretic measure instead of a raw count.
    """
    if not routes:
        return 0.0
    counts = defaultdict(int)
    for r in routes:
        counts[r] += 1
    total = len(routes)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def label_attackers(df: pd.DataFrame, attacker_users: list) -> pd.DataFrame:
    """
    Attach ground-truth labels for Precision/Recall/F1/ROC evaluation, based on
    the known identities used in the controlled attack-scenario runs (Phase 1 of
    DAY_BY_DAY_PLAN.md). Everything else is treated as legitimate traffic.
    """
    df = df.copy()
    df["is_attack"] = df["user_id"].isin(attacker_users).astype(int)
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="Path to exported gateway log CSV")
    parser.add_argument("--output", required=True, help="Path to write the feature CSV")
    parser.add_argument("--count-window", type=float, default=5.0, help="Seconds for req_count window (default: 5)")
    parser.add_argument("--context-window", type=float, default=60.0, help="Seconds for denied_ratio/route_entropy window (default: 60)")
    parser.add_argument("--attacker-users", default="", help="Comma-separated usernames to label as ground-truth attack traffic")
    args = parser.parse_args()

    events = load_gateway_events(args.input)
    print(f"Loaded {len(events)} gateway events across {events['user_id'].nunique()} users")

    features = compute_features(events, args.count_window, args.context_window)

    if args.attacker_users.strip():
        attacker_list = [u.strip() for u in args.attacker_users.split(",") if u.strip()]
        features = label_attackers(features, attacker_list)
        print(f"Labeled {features['is_attack'].sum()} rows as attack traffic "
              f"({attacker_list})")

    features.to_csv(args.output, index=False)
    print(f"Wrote {len(features)} feature rows to {args.output}")
    print("\nColumns ready for scikit-learn:")
    print("  X = features[['req_count_5s', 'denied_ratio', 'route_entropy']]")
    if "is_attack" in features.columns:
        print("  y = features['is_attack']  # for Precision/Recall/F1/ROC evaluation")


if __name__ == "__main__":
    main()
