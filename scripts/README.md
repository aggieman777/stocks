# scripts/

Deterministic, read-only helpers for the Investment DD workflows. None of
these place, cancel, or modify orders, or change target allocations — they
only compute/compare from CSVs (or, for `qqq_ta_log.py`, from external
market data) and print/write a report.

- `portfolio_weighting_check.py` — validates a Top20-style CSV (rank,
  ticker, target_allocation_pct, prior_allocation_pct) against the
  10/5/2.5 tier weights, ±0.5pp deadband, and 100% total. No network.
- `dd_snapshot_diff.py` — diffs two Top20-style CSV snapshots (old vs new)
  for added/removed tickers and rank/weight changes. No network.
- `qqq_ta_log.py` — fetches QQQ/NASDAQ-100 constituents (7-day cache) and
  computes price/200D-MA/volatility/volume per ticker via yfinance.
  **Requires outbound network access to Yahoo Finance and to Wikipedia/
  Invesco for the constituent list.** As of 2026-07-29 this repo's default
  Claude Code Remote environment blocks both (org network policy denies
  the CONNECT tunnel, confirmed via direct curl/yfinance/WebFetch testing)
  — this script will report every ticker "unavailable" if run there. It
  works in any environment with normal outbound HTTPS (e.g. run locally).

Install: `pip install -r scripts/requirements.txt` (only needed for
`qqq_ta_log.py`; the other two are stdlib-only).
