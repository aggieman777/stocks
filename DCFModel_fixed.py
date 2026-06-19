"""
DCFModel_fixed.py

A more robust DCFModel implementation that is safer with yfinance data and provides
better defaults and fallbacks. This file is added as an optional improved DCF implementation.

Usage:
    python DCFModel_fixed.py --ticker KO

Dependencies: numpy, pandas, yfinance
"""
import warnings
import argparse
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

def safe_row(df, names):
    for n in names:
        if n in df.index:
            return df.loc[n].dropna()
    raise KeyError(f"None of {names} found in DataFrame index: {list(df.index[:20])}")

class DCFModel:
    def __init__(self, ticker, terminal_growth=0.03, riskfree_ticker="^TNX", market_ticker="VTI"):
        self.ticker = ticker.upper()
        self.terminal_growth = float(terminal_growth)
        self.riskfree_ticker = riskfree_ticker
        self.market_ticker = market_ticker

        self.stock = yf.Ticker(self.ticker)
        self.is_ann = getattr(self.stock, "financials", pd.DataFrame())
        self.bs_ann = getattr(self.stock, "balance_sheet", pd.DataFrame())
        self.cf_ann = getattr(self.stock, "cashflow", pd.DataFrame())

        self.info = getattr(self.stock, "info", {})

        self.market_cap = self.info.get("marketCap", np.nan)
        self.debt = self.info.get("totalDebt", 0) or 0
        self.cash = self.info.get("totalCash", 0) or 0
        self.shares = self.info.get("sharesOutstanding", np.nan)
        self.beta = self.info.get("beta", np.nan)

        try:
            rf_t = yf.Ticker(self.riskfree_ticker)
            rf_info = rf_t.info
            rf_val = rf_info.get("previousClose", None)
            if rf_val is None:
                self.risk_free = 0.02
            else:
                self.risk_free = rf_val / 100.0 if rf_val > 0.5 else rf_val
        except Exception:
            self.risk_free = 0.02

        self.market_return = self._estimate_market_return(self.market_ticker)

        self._prepare_historical_metrics()

        self.project_years = 5
        self.future_revenue = self._project_revenue()
        self.future_ebit = self._project_ebit()
        self.future_tax = self._project_tax()
        self.ebiat = self.future_ebit - self.future_tax
        self.future_da = self._project_da()
        self.future_capex = self._project_capex()
        self.future_nwc = self._project_nwc()
        self.future_fcf = self.ebiat + self.future_da - self.future_capex - self.future_nwc

        self.wacc = self._wacc()
        self.terminal_value = self._terminal_value()
        self.enterprise_value = self._discounted_cashflow()
        self.implied_share_price = self._implied_share_price()
        self.current_price = self.info.get("previousClose", np.nan)
        self.margin_of_safety = ((self.implied_share_price - self.current_price) / self.current_price) if (self.current_price and not np.isnan(self.current_price)) else np.nan

    def _estimate_market_return(self, market_ticker):
        try:
            hist = yf.download(market_ticker, period="5y", progress=False)["Adj Close"].dropna()
            if len(hist) < 2:
                return 0.08
            years = (hist.index[-1] - hist.index[0]).days / 365.25
            total_ret = hist.iloc[-1] / hist.iloc[0] - 1
            return total_ret / years
        except Exception:
            return 0.08

    def _prepare_historical_metrics(self):
        try:
            revenue = safe_row(self.is_ann, ["Total Revenue", "Revenue", "totalRevenue"])
            self.revenue_hist = revenue.astype(float)
        except KeyError:
            raise RuntimeError("Revenue row not found in financials. yfinance financials missing for this ticker.")

        try:
            ebit = safe_row(self.is_ann, ["EBIT", "Operating Income", "OperatingIncome"])
            self.ebit_hist = ebit.astype(float)
        except KeyError:
            try:
                ni = safe_row(self.is_ann, ["Net Income", "NetIncome"])
                self.ebit_hist = ni.astype(float)
            except KeyError:
                raise RuntimeError("EBIT or Net Income not found in financials.")

        try:
            tax = safe_row(self.is_ann, ["Income Tax Expense", "Tax Provision", "Provision for Income Taxes"])
            self.tax_hist = tax.astype(float)
        except KeyError:
            self.tax_hist = pd.Series([0.21], index=[self.revenue_hist.index[0]])

        try:
            interest = safe_row(self.is_ann, ["Interest Expense", "InterestExpense"])
            self.interest_hist = interest.astype(float)
        except KeyError:
            self.interest_hist = pd.Series([0.0], index=[self.revenue_hist.index[0]])

        try:
            da = safe_row(self.cf_ann, ["Depreciation & Amortization", "Depreciation And Amortization", "Depreciation"])
            self.da_hist = da.astype(float)
        except KeyError:
            self.da_hist = pd.Series([0.0], index=[self.revenue_hist.index[0]])
        try:
            capex = safe_row(self.cf_ann, ["Capital Expenditure", "Capital Expenditures", "Capital Expenditures (CAPEX)", "Capital Expenditures"])
            self.capex_hist = capex.astype(float)
        except KeyError:
            self.capex_hist = pd.Series([0.0], index=[self.revenue_hist.index[0]])
        try:
            nwc = safe_row(self.cf_ann, ["Change In Working Capital", "Change in Working Capital", "Changes In Working Capital"])
            self.nwc_hist = nwc.astype(float)
        except KeyError:
            self.nwc_hist = pd.Series([0.0], index=[self.revenue_hist.index[0]])

    def _historical_growth(self, series, years=3):
        s = series.dropna()
        if len(s) < 2:
            return 0.05
        s = s.iloc[:years+1]
        pct = s.pct_change().dropna()
        if len(pct) == 0:
            return 0.05
        return float(pct.median())

    def _project_revenue(self):
        hist_growth = self._historical_growth(self.revenue_hist, years=3)
        base = float(self.revenue_hist.iloc[0])
        rates = [(1 + hist_growth) ** (i+1) for i in range(self.project_years)]
        return pd.Series([base * r for r in rates], index=range(1, self.project_years+1))

    def _project_ebit(self):
        ebit_margin = (self.ebit_hist / self.revenue_hist).replace([np.inf, -np.inf], np.nan).dropna()
        if len(ebit_margin) == 0:
            margin = 0.10
        else:
            margin = float(np.nanmedian(ebit_margin))
        return self.future_revenue * margin

    def _project_tax(self):
        ebit_for_tax = self.ebit_hist.copy()
        tax_rate_series = (self.tax_hist / ebit_for_tax).replace([np.inf, -np.inf], np.nan).dropna()
        tax_rate = float(np.nanmedian(tax_rate_series)) if len(tax_rate_series) else 0.21
        tax_rate = max(0.0, min(0.5, tax_rate))
        return self._project_ebit() * tax_rate

    def _project_da(self):
        da_margin = (self.da_hist / self.revenue_hist).replace([np.inf, -np.inf], np.nan).dropna()
        margin = float(np.nanmedian(da_margin)) if len(da_margin) else 0.03
        return self.future_revenue * margin

    def _project_capex(self):
        capex_margin = (self.capex_hist / self.revenue_hist).replace([np.inf, -np.inf], np.nan).dropna()
        margin = float(np.nanmedian(capex_margin)) if len(capex_margin) else 0.05
        return self.future_revenue * margin

    def _project_nwc(self):
        nwc_margin = (self.nwc_hist / self.revenue_hist).replace([np.inf, -np.inf], np.nan).dropna()
        margin = float(np.nanmedian(nwc_margin)) if len(nwc_margin) else 0.0
        return self.future_revenue * margin

    def _wacc(self):
        debt_val = float(self.debt)
        equity_val = float(self.market_cap) if not pd.isna(self.market_cap) else 0.0
        total = debt_val + equity_val
        if total <= 0:
            w_d = 0.0
            w_e = 1.0
        else:
            w_d = debt_val / total
            w_e = equity_val / total
        cost_of_debt = 0.03
        try:
            int_exp = float(self.interest_hist.iloc[0])
            cost_of_debt = abs(int_exp) / debt_val if debt_val > 0 else 0.03
        except Exception:
            cost_of_debt = 0.03
        beta = float(self.beta) if not pd.isna(self.beta) else 1.0
        cost_of_equity = self.risk_free + beta * (self.market_return - self.risk_free)
        try:
            tax_rate = float((self.tax_hist / self.ebit_hist).replace([np.inf, -np.inf], np.nan).dropna().median())
            tax_rate = max(0.0, min(0.5, tax_rate))
        except Exception:
            tax_rate = 0.21
        return w_d * cost_of_debt * (1 - tax_rate) + w_e * cost_of_equity

    def _terminal_value(self):
        return (self.future_fcf[4] * (1 + self.terminal_growth)) / (self.wacc - self.terminal_growth)

    def _discounted_cashflow(self):
        DiscountedCashFlow = sum(
            pd.Series((fcf / ((1 + self.wacc) ** (0.5 + i))) for i, fcf in enumerate(self.future_fcf))
        )
        DiscountedTerminalValue = self.TerminalValue / ((1 + self.wacc) ** 5)
        EnterpriseValue = DiscountedCashFlow + DiscountedTerminalValue
        return EnterpriseValue

    def _CalculateImpliedSharePrice(self):
        EquityValue = self.EnterpriseValue - self.debt + self.cash
        ImpliedSharePrice = EquityValue / self.shares
        return ImpliedSharePrice

    def _implied_share_price(self):
        ev = float(self.enterprise_value)
        equity = ev - float(self.debt) + float(self.cash)
        if pd.isna(self.shares) or self.shares == 0:
            raise RuntimeError("Shares outstanding not available to compute per-share price.")
        return equity / float(self.shares)

    def summary(self):
        out = {
            "Ticker": self.ticker,
            "Current Price": self.current_price,
            "Implied Share Price": round(self.implied_share_price, 2),
            "Margin of Safety": f"{self.margin_of_safety:.2%}",
            "WACC": f"{self.wacc:.2%}",
            "Terminal Value": round(self.terminal_value, 2),
            "Enterprise Value": round(self.enterprise_value, 2),
        }
        return out

if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--TGR", dest="TGR", default=0.03, type=float)
    parser.add_argument("--riskfree", dest="RiskFree", default="^TNX")
    parser.add_argument("--market", dest="MarketReturn", default="VTI")
    args = parser.parse_args()

    model = DCFModel(args.ticker, terminal_growth=args.TGR, riskfree_ticker=args.RiskFree, market_ticker=args.MarketReturn)
    print(model.summary())
