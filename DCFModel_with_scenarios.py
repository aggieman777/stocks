"""
DCFModel_with_scenarios.py

Merged scenario-driven DCF model that reads Investment DD CSV and projects FCF under bear/base/bull cases.

Usage examples:
    python DCFModel_with_scenarios.py --ticker NVDA --dd_csv Investment_DD_Extended_DCF_NPV_v10_2.csv
    python DCFModel_with_scenarios.py --ticker MU   --dd_csv Investment_DD_Extended_DCF_NPV_v10_2.csv

Dependencies:
    - numpy
    - pandas
    - yfinance

Place this file in the repository root and run with the --dd_csv pointing to your Investment DD CSV file.
"""
import argparse
import re
import math
import numpy as np
import pandas as pd
import yfinance as yf
import warnings

warnings.filterwarnings("ignore")

def parse_range_midpoint(token: str):
    token = token.strip().replace("+","")
    m = re.findall(r'(-?\d+\.?\d*)\s*-\s*(-?\d+\.?\d*)\%?', token)
    if m:
        a, b = m[0]
        return (float(a) + float(b)) / 2.0 / 100.0
    m2 = re.search(r'(-?\d+\.?\d*)\%?', token)
    if m2:
        return float(m2.group(1)) / 100.0
    return None

def parse_growth_string(s: str, years=5):
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return [0.05] * years
    if not isinstance(s, str):
        try:
            return [float(s)] * years
        except Exception:
            return [0.05] * years
    s_clean = s.lower().replace(" ", "")
    if 'then' in s_clean:
        parts = re.split(r'then', s_clean)
    elif ';' in s_clean:
        parts = s_clean.split(';')
    elif ',' in s_clean and '%' in s_clean and '-' in s_clean:
        parts = s_clean.split(',')
    else:
        parts = [s_clean]
    parsed = []
    for p in parts:
        m = re.search(r'(-?\d+\.?\d*\s*-\s*-?\d+\.?\d*)\%?', p)
        if m:
            parsed.append(parse_range_midpoint(m.group(0)))
            continue
        m2 = re.search(r'(-?\d+\.?\d*)\%?', p)
        if m2:
            parsed.append(float(m2.group(1)) / 100.0)
            continue
    if len(parsed) == 0:
        nums = re.findall(r'(-?\d+\.?\d*)', s_clean)
        if nums:
            val = float(nums[0]) / 100.0
            return [val] * years
        return [0.05] * years
    if len(parsed) == 1:
        return [parsed[0]] * years
    g = []
    first = parsed[0]
    second = parsed[1] if len(parsed) > 1 else parsed[0]
    g.extend([first] * min(2, years))
    remaining = years - len(g)
    g.extend([second] * remaining)
    return g

def safe_get_info_field(ticker_obj, *keys):
    for k in keys:
        if k in ticker_obj.info and ticker_obj.info[k] is not None:
            return ticker_obj.info[k]
    return None

def seed_last_values(ticker_obj):
    info = ticker_obj.info
    rev = None
    for key in ("totalRevenue","revenue","TotalRevenue"):
        if key in info and info[key] not in (None, 0):
            rev = info[key]
            break
    if rev is None:
        try:
            fin = getattr(ticker_obj, "financials", None)
            if fin is not None and not fin.empty:
                if "Total Revenue" in fin.index:
                    rev_series = fin.loc["Total Revenue"].dropna()
                elif "Revenue" in fin.index:
                    rev_series = fin.loc["Revenue"].dropna()
                else:
                    candidates = fin.apply(lambda col: col.abs().max(), axis=1)
                    top_idx = candidates.idxmax()
                    rev_series = fin.loc[top_idx].dropna()
                last_val = float(rev_series.iloc[0])
                rev = last_val
        except Exception:
            rev = None
    fcf = safe_get_info_field(ticker_obj, "freeCashflow")
    if fcf is None:
        try:
            cf = getattr(ticker_obj, "cashflow", None)
            if cf is not None and not cf.empty:
                candidates = ["Total Cash From Operating Activities", "Total Cash From Operations", "Net Cash Provided by Operating Activities", "Operating Cash Flow", "Net Cash From Operating Activities"]
                op = None
                for c in candidates:
                    if c in cf.index:
                        op = cf.loc[c].dropna()
                        break
                if op is None:
                    op = cf.iloc[0].dropna()
                cap_keys = ["Capital Expenditure", "Capital Expenditures", "Capital Expenditure (CAPEX)", "Capital Expenditures (CapEx)"]
                cap = None
                for ck in cap_keys:
                    if ck in cf.index:
                        cap = cf.loc[ck].dropna()
                        break
                if cap is None:
                    numeric_sums = cf.sum(axis=1)
                    cap_row_idx = numeric_sums.idxmin()
                    cap = cf.loc[cap_row_idx].dropna()
                last_op = float(op.iloc[0])
                last_cap = float(cap.iloc[0])
                fcf = last_op + last_cap
        except Exception:
            fcf = None
    if rev is None or rev == 0:
        rev = 1.0
    if fcf is None:
        fcf = rev * 0.08
    return float(rev), float(fcf)

def parse_csv_dd(dd_csv_path):
    df = pd.read_csv(dd_csv_path, dtype=str)
    if "ticker" in df.columns:
        df['ticker'] = df['ticker'].str.upper()
        df = df.set_index('ticker')
    else:
        if "Exchange:Ticker" in df.columns:
            df['ticker'] = df['Exchange:Ticker'].apply(lambda v: str(v).split(':')[-1].strip().upper())
            df = df.set_index('ticker')
    return df

def compute_wacc_from_csv_or_defaults(row, ticker_obj):
    if isinstance(row, pd.Series) and 'wacc' in row.index:
        try:
            wacc_raw = row['wacc']
            if isinstance(wacc_raw, str) and wacc_raw.strip() != '':
                val = parse_range_midpoint(wacc_raw)
                if val is not None:
                    return val
        except Exception:
            pass
    info = ticker_obj.info
    rf = safe_get_info_field(yf.Ticker("^TNX"), "previousClose")
    if rf is None:
        rf = 0.02
    else:
        try:
            rf = float(rf) / 100.0
        except:
            rf = 0.02
    beta = info.get("beta", 1.0) or 1.0
    market_ret = 0.08
    try:
        market_ret = yf.Ticker("VTI").info.get("threeYearAverageReturn", None) or 0.08
        if market_ret and market_ret > 0.5:
            market_ret = market_ret / 100.0
    except Exception:
        market_ret = 0.08
    cost_of_equity = rf + beta * (market_ret - rf)
    debt = info.get("totalDebt", 0) or 0
    interest = 0.0
    try:
        inc = getattr(ticker_obj, "financials", None)
        if inc is not None and not inc.empty:
            if "Interest Expense" in inc.index:
                interest = abs(float(inc.loc["Interest Expense"].iloc[0]))
    except Exception:
        interest = 0.0
    cost_of_debt = 0.03
    if debt and interest:
        cost_of_debt = interest / debt
    tax_rate = 0.21
    try:
        inc = getattr(ticker_obj, "financials", None)
        if inc is not None and not inc.empty:
            if "Tax Provision" in inc.index:
                tax_val = float(inc.loc["Tax Provision"].iloc[0])
                ebit_val = None
                if "EBIT" in inc.index:
                    ebit_val = float(inc.loc["EBIT"].iloc[0])
                elif "Operating Income" in inc.index:
                    ebit_val = float(inc.loc["Operating Income"].iloc[0])
                if ebit_val and ebit_val != 0:
                    tax_rate = max(0.0, min(0.5, tax_val / ebit_val))
    except Exception:
        tax_rate = 0.21
    marketcap = info.get("marketCap", 0) or 0
    total = marketcap + debt
    if total <= 0:
        w_d = 0.0
        w_e = 1.0
    else:
        w_d = debt / total
        w_e = marketcap / total
    wacc = w_d * cost_of_debt * (1 - tax_rate) + w_e * cost_of_equity
    if wacc <= 0 or math.isnan(wacc):
        return 0.08
    return float(wacc)

def run_dcf_for_scenario(last_revenue, last_fcf, revenue_growth_rates, fcf_growth_rates, wacc, terminal_growth, shares_out, project_years=5):
    future_revenue = []
    rev = last_revenue
    for g in revenue_growth_rates:
        rev = rev * (1 + g)
        future_revenue.append(rev)
    future_fcf = []
    fcf = last_fcf
    for g in fcf_growth_rates:
        fcf = fcf * (1 + g)
        future_fcf.append(fcf)
    pv_fcf = 0.0
    for i, f in enumerate(future_fcf, start=1):
        pv = f / ((1 + wacc) ** i)
        pv_fcf += pv
    last_year_fcf = future_fcf[-1]
    if wacc <= terminal_growth:
        denom = max(1e-6, wacc - terminal_growth)
    else:
        denom = (wacc - terminal_growth)
    terminal_value = last_year_fcf * (1 + terminal_growth) / denom
    pv_terminal = terminal_value / ((1 + wacc) ** project_years)
    enterprise_value = pv_fcf + pv_terminal
    return {
        "future_revenue": future_revenue,
        "future_fcf": future_fcf,
        "pv_fcf": pv_fcf,
        "pv_terminal": pv_terminal,
        "terminal_value": terminal_value,
        "enterprise_value": enterprise_value
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True, help="Ticker symbol")
    parser.add_argument("--dd_csv", required=True, help="Path to Investment_DD_Extended_DCF_NPV_v10_2.csv")
    parser.add_argument("--years", default=5, type=int, help="Projection years (default 5)")
    parser.add_argument("--use_csv_wacc", action="store_true", help="If set, use WACC from CSV when present")
    args = parser.parse_args()

    dd = parse_csv_dd(args.dd_csv)
    ticker = args.ticker.upper()
    if ticker not in dd.index:
        print(f"Ticker {ticker} not found in DD CSV index. Available tickers (sample 50): {list(dd.index[:50])}")
    row = dd.loc[ticker] if ticker in dd.index else pd.Series()

    print(f"Seeding data for {ticker} from yfinance...")
    tk = yf.Ticker(ticker)
    last_rev, last_fcf = seed_last_values(tk)
    shares = tk.info.get("sharesOutstanding", None)
    if shares is None or shares == 0:
        print("Warning: sharesOutstanding missing — per-share outputs will be N/A until you supply shares or fix the ticker data.")
    scenarios = {
        "bear": {
            "rev_str": row.get("revenue_growth_bear", None) if not row.empty else None,
            "fcf_str": row.get("eps_fcf_growth_bear", None) if not row.empty else None
        },
        "base": {
            "rev_str": row.get("revenue_growth_base", None) if not row.empty else None,
            "fcf_str": row.get("eps_fcf_growth_base", None) if not row.empty else None
        },
        "bull": {
            "rev_str": row.get("revenue_growth_bull", None) if not row.empty else None,
            "fcf_str": row.get("eps_fcf_growth_bull", None) if not row.empty else None
        }
    }
    for name, s in scenarios.items():
        rev_s = s["rev_str"]
        fcf_s = s["fcf_str"]
        rev_rates = parse_growth_string(rev_s, years=args.years) if rev_s is not None else [0.05]*args.years
        fcf_rates = parse_growth_string(fcf_s, years=args.years) if fcf_s is not None else [0.10]*args.years
        scenarios[name]['rev_rates'] = rev_rates
        scenarios[name]['fcf_rates'] = fcf_rates

    terminal_growth = 0.03
    try:
        tgr = row.get("terminal_growth", None) if not row.empty else None
        if tgr is not None and isinstance(tgr, str) and tgr.strip() != '':
            val = parse_range_midpoint(tgr)
            if val is not None:
                terminal_growth = val
    except Exception:
        terminal_growth = 0.03

    wacc = None
    if args.use_csv_wacc and not row.empty and 'wacc' in row.index and row['wacc'] and str(row['wacc']).strip() != '':
        maybe = parse_range_midpoint(row['wacc'])
        if maybe is not None:
            wacc = maybe
    if wacc is None:
        wacc = compute_wacc_from_csv_or_defaults(row, tk)
    total_debt = tk.info.get("totalDebt", 0) or 0
    cash = tk.info.get("totalCash", 0) or 0
    last_price = tk.info.get("previousClose", None)
    print(f"Inputs: last_revenue={last_rev:,.0f}, last_fcf={last_fcf:,.0f}, shares={shares}, debt={total_debt}, cash={cash}")
    results = {}
    for name, s in scenarios.items():
        res = run_dcf_for_scenario(last_rev, last_fcf, s['rev_rates'], s['fcf_rates'], wacc, terminal_growth, shares, project_years=args.years)
        ev = res['enterprise_value']
        equity_value = ev - float(total_debt) + float(cash)
        per_share = equity_value / float(shares) if shares and not math.isnan(shares) and shares != 0 else None
        margin_of_safety = ((per_share - last_price) / last_price) if (per_share is not None and last_price and last_price > 0) else None
        results[name] = {
            "pv_fcf": res['pv_fcf'],
            "pv_terminal": res['pv_terminal'],
            "enterprise_value": ev,
            "equity_value": equity_value,
            "implied_share_price": per_share,
            "margin_of_safety": margin_of_safety,
            "future_revenue": res['future_revenue'],
            "future_fcf": res['future_fcf'],
            "wacc": wacc,
            "terminal_growth": terminal_growth
        }

    print("\n\nDCF Scenario Summary for", ticker)
    header = ["Scenario","WACC","TGR","PV FCF","PV Terminal","Enterprise Value","Equity Value","Implied $/sh","Price","Margin of Safety"]
    print("{:<8} {:>6} {:>5} {:>12} {:>12} {:>15} {:>14} {:>12} {:>10} {:>8}".format(*header))
    for name in ["bear","base","bull"]:
        r = results[name]
        per = r['implied_share_price']
        mos = r['margin_of_safety']
        print("{:<8} {:>6.2%} {:>5.2%} {:>12,.0f} {:>12,.0f} {:>15,.0f} {:>14,.0f} {:>12,.2f} {:>10,.2f} {:>8}".format(
            name, r['wacc'], r['terminal_growth'], r['pv_fcf'], r['pv_terminal'], r['enterprise_value'], r['equity_value'],
            per if per is not None else float('nan'), last_price if last_price is not None else float('nan'),
            f"{r['margin_of_safety']:.2%}" if mos is not None else "N/A"
        ))
    print("\nNotes:")
    print("- Growth strings parsed from DD CSV into yearly rates; verify parsed rates before acting.")
    print("- If sharesOutstanding or meaningful cash/debt info is missing, per-share values will be invalid.")
    print("- This is screen-grade: review raw 'future_revenue' and 'future_fcf' outputs in results for audit.")

if __name__ == "__main__":
    main()
