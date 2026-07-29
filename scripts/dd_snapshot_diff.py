#!/usr/bin/env python3
"""Deterministic diff between two Top20-style DD snapshot CSVs.

Compares ticker membership and target_allocation_pct between an old and a
new Investment_DD_Top20_Allocation_*.csv, so the daily DD-snapshot review
doesn't rely on an LLM eyeballing two files for what changed. Invents
nothing: if a file lacks the required columns, it fails loudly rather than
guessing.

Usage:
    python3 dd_snapshot_diff.py old_top20.csv new_top20.csv
"""
import argparse
import csv
import sys

KEY_COLUMNS = ["ticker", "rank", "target_allocation_pct"]


def load(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in KEY_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{path}: missing required column(s) {missing}. "
                              f"Found: {reader.fieldnames}")
        return {row["ticker"]: row for row in reader}


def diff(old, new, weight_tolerance_pp):
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = []
    for ticker in sorted(set(old) & set(new)):
        old_row, new_row = old[ticker], new[ticker]
        old_w = float(old_row["target_allocation_pct"])
        new_w = float(new_row["target_allocation_pct"])
        old_rank = old_row["rank"]
        new_rank = new_row["rank"]
        weight_delta = new_w - old_w
        if abs(weight_delta) > weight_tolerance_pp or old_rank != new_rank:
            changed.append({
                "ticker": ticker,
                "old_rank": old_rank, "new_rank": new_rank,
                "old_weight": old_w, "new_weight": new_w,
                "weight_delta": weight_delta,
            })
    return added, removed, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_csv")
    parser.add_argument("new_csv")
    parser.add_argument("--weight-tolerance-pp", type=float, default=0.01)
    args = parser.parse_args()

    old = load(args.old_csv)
    new = load(args.new_csv)
    added, removed, changed = diff(old, new, args.weight_tolerance_pp)

    print(f"Old snapshot: {args.old_csv} ({len(old)} tickers)")
    print(f"New snapshot: {args.new_csv} ({len(new)} tickers)\n")

    if added:
        print(f"ADDED ({len(added)}): {', '.join(added)}")
    if removed:
        print(f"REMOVED ({len(removed)}): {', '.join(removed)}")
    if changed:
        print(f"\nCHANGED ({len(changed)}):")
        for c in changed:
            print(f"  {c['ticker']}: rank {c['old_rank']}->{c['new_rank']}, "
                  f"weight {c['old_weight']}%->{c['new_weight']}% "
                  f"({c['weight_delta']:+.2f}pp)")
    if not (added or removed or changed):
        print("No membership or weight changes detected.")

    if not sys.stdout.isatty():
        return
    print(f"\nUnchanged tickers: {len(set(old) & set(new)) - len(changed)}")


if __name__ == "__main__":
    main()
