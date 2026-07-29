#!/usr/bin/env python3
"""Deterministic Top-20 portfolio weighting / guardrail check.

Operates only on a supplied Top20-style CSV (columns: rank, ticker,
target_allocation_pct, prior_allocation_pct — the core_immutable columns
per the FI-022 column-ownership matrix). Computes guardrail violations;
invents no membership, weights, or prices of its own.

Checks:
  - Row count matches --expected-rows (default 20)
  - target_allocation_pct sums to ~100% (tolerance --sum-tolerance-pct)
  - Each target_allocation_pct falls within --deadband-pp of one of the
    allowed tier weights (default 10 / 5 / 2.5)
  - abs(target_allocation_pct - prior_allocation_pct) exceeding
    --deadband-pp is flagged as a pending rebalance, not executed

Usage:
    python3 portfolio_weighting_check.py path/to/Investment_DD_Top20_Allocation_vX.csv
"""
import argparse
import csv
import sys


REQUIRED_COLUMNS = ["rank", "ticker", "target_allocation_pct", "prior_allocation_pct"]


def load_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise SystemExit(f"Missing required column(s) {missing} in {path}. "
                          f"Found columns: {reader.fieldnames}")
    return rows


def to_float(value, field, ticker):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Non-numeric {field}={value!r} for ticker={ticker!r}")


def nearest_tier(value, tiers):
    return min(tiers, key=lambda t: abs(t - value))


def run_checks(rows, expected_rows, tiers, deadband_pp, sum_tolerance_pct):
    findings = []

    if len(rows) != expected_rows:
        findings.append({
            "severity": "FAIL",
            "check": "row_count",
            "detail": f"expected {expected_rows} rows, found {len(rows)}",
        })

    total = 0.0
    for row in rows:
        ticker = row["ticker"]
        target = to_float(row["target_allocation_pct"], "target_allocation_pct", ticker)
        prior = to_float(row["prior_allocation_pct"], "prior_allocation_pct", ticker)
        total += target

        nearest = nearest_tier(target, tiers)
        if abs(target - nearest) > deadband_pp:
            findings.append({
                "severity": "WARN",
                "check": "off_tier_weight",
                "ticker": ticker,
                "detail": f"target_allocation_pct={target} is {abs(target - nearest):.2f}pp "
                          f"from nearest documented tier ({nearest})",
            })

        drift = target - prior
        if abs(drift) > deadband_pp:
            findings.append({
                "severity": "INFO",
                "check": "pending_rebalance",
                "ticker": ticker,
                "detail": f"target ({target}) vs prior ({prior}) drift {drift:+.2f}pp "
                          f"exceeds ±{deadband_pp}pp deadband — flagged for review, not executed",
            })

    if abs(total - 100.0) > sum_tolerance_pct:
        findings.append({
            "severity": "FAIL",
            "check": "total_allocation",
            "detail": f"target_allocation_pct sums to {total:.2f}%, expected 100% "
                      f"(tolerance ±{sum_tolerance_pct}pp)",
        })

    return findings, total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--expected-rows", type=int, default=20)
    parser.add_argument("--tiers", type=float, nargs="+", default=[10.0, 5.0, 2.5])
    parser.add_argument("--deadband-pp", type=float, default=0.5)
    parser.add_argument("--sum-tolerance-pct", type=float, default=0.1)
    args = parser.parse_args()

    rows = load_rows(args.csv_path)
    findings, total = run_checks(rows, args.expected_rows, args.tiers,
                                  args.deadband_pp, args.sum_tolerance_pct)

    print(f"Rows checked: {len(rows)} | Total target allocation: {total:.2f}%\n")
    if not findings:
        print("No guardrail violations found.")
        return

    for f in sorted(findings, key=lambda x: {"FAIL": 0, "WARN": 1, "INFO": 2}[x["severity"]]):
        ticker = f.get("ticker", "-")
        print(f"[{f['severity']}] {f['check']} ticker={ticker}: {f['detail']}")

    if any(f["severity"] == "FAIL" for f in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
