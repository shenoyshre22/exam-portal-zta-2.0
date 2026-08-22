"""
anomaly_detection.py

Runs two anomaly detectors on the output of feature_engineering.py and reports
Precision/Recall/F1/ROC-AUC for both, side by side:

  1. Naive threshold baseline -- a simple rule: flag a row as anomalous if
     req_count_5s, denied_ratio, or route_entropy exceeds a fixed cutoff. No
     training, no learned structure, just hand-picked thresholds.

  2. Isolation Forest -- scikit-learn, trained offline on the same three
     features, no live scoring inside any request path.

This comparison exists to answer, honestly, a fair question about the paper:
"does the ML model actually buy you anything over a simple rule?" If Isolation
Forest doesn't clearly beat the naive baseline, that's a real result worth
reporting as-is, not a result to hide.

Usage:
    python anomaly_detection.py --features features.csv --output metrics.json

Requires the input CSV to have an `is_attack` label column, i.e. features.csv
must have been produced with feature_engineering.py's --attacker-users flag.
"""

import argparse
import json

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score

FEATURE_COLUMNS = ["req_count_5s", "denied_ratio", "route_entropy"]


def naive_threshold_baseline(
    df: pd.DataFrame,
    req_count_threshold: float = 5,
    denied_ratio_threshold: float = 0.3,
    route_entropy_threshold: float = 4,
) -> pd.Series:
    """
    Flags a row anomalous if it crosses any single threshold. Thresholds are
    picked by eyeballing legitimate traffic (a real exam session rarely fires
    more than a handful of requests in 5s, rarely gets denied, and touches a
    small number of routes) -- not tuned against the attack labels, so this
    is a genuinely naive comparator, not a strawman.
    """
    return (
        (df["req_count_5s"] > req_count_threshold)
        | (df["denied_ratio"] > denied_ratio_threshold)
        | (df["route_entropy"] > route_entropy_threshold)
    ).astype(int)


def isolation_forest_detector(df: pd.DataFrame, contamination: float = "auto", random_state: int = 42) -> pd.Series:
    """
    Fits IsolationForest on the 3 features and returns a 0/1 flag per row
    (1 = anomalous). Trained and scored entirely offline on the exported
    dataset -- this never runs inside the gateway's request path.
    """
    model = IsolationForest(contamination=contamination, random_state=random_state)
    X = df[FEATURE_COLUMNS]
    raw = model.fit_predict(X)  # returns 1 for inlier, -1 for outlier
    return pd.Series((raw == -1).astype(int), index=df.index)


def evaluate(y_true: pd.Series, y_pred: pd.Series, label: str) -> dict:
    metrics = {
        "detector": label,
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
    }
    # ROC-AUC needs both classes present in y_true to be meaningful
    if y_true.nunique() == 2:
        metrics["roc_auc"] = round(roc_auc_score(y_true, y_pred), 4)
    else:
        metrics["roc_auc"] = None
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", required=True, help="Path to features.csv from feature_engineering.py")
    parser.add_argument("--output", default=None, help="Optional path to write metrics as JSON")
    parser.add_argument("--contamination", default="auto", help="IsolationForest contamination param (float or 'auto')")
    args = parser.parse_args()

    df = pd.read_csv(args.features)
    if "is_attack" not in df.columns:
        raise ValueError(
            "features.csv has no 'is_attack' column. Re-run feature_engineering.py "
            "with --attacker-users to label ground truth before evaluating detectors."
        )

    missing = set(FEATURE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"features.csv is missing expected columns: {sorted(missing)}")

    y_true = df["is_attack"]
    print(f"Loaded {len(df)} rows, {y_true.sum()} labeled as attack traffic ({y_true.mean():.1%})")

    contamination = args.contamination
    if contamination != "auto":
        contamination = float(contamination)

    results = []

    naive_pred = naive_threshold_baseline(df)
    results.append(evaluate(y_true, naive_pred, "naive_threshold_baseline"))

    iso_pred = isolation_forest_detector(df, contamination=contamination)
    results.append(evaluate(y_true, iso_pred, "isolation_forest"))

    print("\n{:<28} {:>10} {:>10} {:>10} {:>10}".format("Detector", "Precision", "Recall", "F1", "ROC-AUC"))
    for r in results:
        roc = f"{r['roc_auc']:.4f}" if r["roc_auc"] is not None else "n/a"
        print("{:<28} {:>10.4f} {:>10.4f} {:>10.4f} {:>10}".format(r["detector"], r["precision"], r["recall"], r["f1"], roc))

    if results[1]["f1"] <= results[0]["f1"]:
        print(
            "\nNote: Isolation Forest did not beat the naive threshold baseline on F1 for "
            "this dataset. Report this honestly in Results rather than tuning contamination "
            "until it does -- it's a real, defensible finding about this feature set/traffic mix."
        )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nWrote metrics to {args.output}")


if __name__ == "__main__":
    main()
