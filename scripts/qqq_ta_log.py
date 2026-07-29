#!/usr/bin/env python3
"""Deterministic QQQ constituent technical-analysis log.

Fetches (with a 7-day cache) the current QQQ/NASDAQ-100 constituent list,
then for each ticker computes price, 200-day SMA, 20-day annualized
historical volatility, and latest volume via yfinance. Emits a Markdown
table. Read-only market-data computation only — places no orders.

Usage:
    pip install --quiet yfinance pandas
    python3 qqq_ta_log.py [--cache-dir DIR] [--out FILE] [--max-age-days N]
"""
import argparse
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".investment_dd_cache"
CACHE_FILE = "qqq_constituents_cache.json"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"


def load_cache(cache_dir: Path, max_age_days: int):
    path = cache_dir / CACHE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        fetched_at = datetime.datetime.fromisoformat(data["fetched_at"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
    age = datetime.datetime.now(datetime.timezone.utc) - fetched_at
    if age > datetime.timedelta(days=max_age_days):
        return None
    return data


def write_cache(cache_dir: Path, tickers: list, source: str):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / CACHE_FILE
    payload = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": source,
        "tickers": tickers,
    }
    path.write_text(json.dumps(payload, indent=2))


def fetch_constituents_from_wikipedia():
    req = urllib.request.Request(WIKIPEDIA_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    tickers = sorted(set(re.findall(r'title="[^"]+"[^>]*>\(?([A-Z]{1,5})\)?', html)))
    tickers = [t for t in re.findall(r">([A-Z]{1,5})</a>", html)]
    seen, ordered = set(), []
    for t in tickers:
        if t not in seen and 1 <= len(t) <= 5:
            seen.add(t)
            ordered.append(t)
    return ordered, WIKIPEDIA_URL


def get_constituents(cache_dir: Path, max_age_days: int):
    cached = load_cache(cache_dir, max_age_days)
    if cached:
        return cached["tickers"], cached["source"], cached["fetched_at"], "cache"
    tickers, source = fetch_constituents_from_wikipedia()
    if not tickers:
        raise RuntimeError("Constituent fetch returned zero tickers; not caching a bad result.")
    write_cache(cache_dir, tickers, source)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return tickers, source, now, "fresh_fetch"


def compute_ta(tickers, batch_size=20):
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance not installed. Run: pip install --quiet yfinance pandas", file=sys.stderr)
        sys.exit(1)

    rows = []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            data = yf.download(batch, period="1y", group_by="ticker", threads=True,
                                progress=False, auto_adjust=False)
        except Exception as exc:  # network/rate-limit failure for this batch
            for t in batch:
                rows.append({"ticker": t, "status": "unavailable", "source": f"yfinance_error: {exc}"})
            continue

        for t in batch:
            try:
                hist = data[t] if len(batch) > 1 else data
            except KeyError:
                rows.append({"ticker": t, "status": "unavailable", "source": "yfinance_no_data"})
                continue
            hist = hist.dropna(subset=["Close"])
            if hist.empty:
                rows.append({"ticker": t, "status": "unavailable", "source": "yfinance_empty"})
                continue
            price = float(hist["Close"].iloc[-1])
            ma200 = hist["Close"].rolling(200).mean().iloc[-1]
            ma200 = float(ma200) if ma200 == ma200 else None  # NaN check
            returns = hist["Close"].pct_change().dropna()
            vol20 = returns.tail(20).std() * (252 ** 0.5) if len(returns) >= 2 else None
            vol20 = float(vol20) if vol20 is not None and vol20 == vol20 else None
            volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist else None
            vs_ma200_pct = ((price / ma200) - 1) * 100 if ma200 else None
            rows.append({
                "ticker": t,
                "status": "ok",
                "price": round(price, 2),
                "ma200": round(ma200, 2) if ma200 else None,
                "vs_ma200_pct": round(vs_ma200_pct, 2) if vs_ma200_pct is not None else None,
                "vol20d_annualized_pct": round(vol20 * 100, 2) if vol20 is not None else None,
                "volume": volume,
                "source": "yfinance",
                "as_of": str(hist.index[-1].date()),
            })
    return rows


def render_markdown(rows, list_source, list_fetched_at, list_mode):
    today = datetime.date.today().isoformat()
    lines = [
        f"# QQQ Constituent TA Log — {today}",
        "",
        f"Constituent list: {list_mode} (source: {list_source}, as-of: {list_fetched_at})",
        "",
        "| Ticker | Price | 200D MA | vs 200D MA | Vol (20D ann.) | Volume | Source | As-of |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("status") != "ok":
            lines.append(f"| {r['ticker']} | unavailable | | | | | {r.get('source', '')} | |")
            continue
        vs = f"{r['vs_ma200_pct']}%" if r["vs_ma200_pct"] is not None else "n/a"
        vol = f"{r['vol20d_annualized_pct']}%" if r["vol20d_annualized_pct"] is not None else "n/a"
        lines.append(
            f"| {r['ticker']} | {r['price']} | {r['ma200']} | {vs} | {vol} | "
            f"{r['volume']} | {r['source']} | {r['as_of']} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    tickers, source, fetched_at, mode = get_constituents(args.cache_dir, args.max_age_days)
    rows = compute_ta(tickers)
    md = render_markdown(rows, source, fetched_at, mode)

    if args.out:
        args.out.write_text(md)
        print(f"Wrote {args.out}")
    else:
        print(md)

    unavailable = [r["ticker"] for r in rows if r.get("status") != "ok"]
    if unavailable:
        print(f"\n{len(unavailable)} unavailable: {', '.join(unavailable)}", file=sys.stderr)


if __name__ == "__main__":
    main()
