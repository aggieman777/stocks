# stocks

DCF stock valuation model with bear/base/bull scenario analysis using Investment DD CSV data.

## Added tools

This branch adds two optional DCF utilities:

- `DCFModel_with_scenarios.py` — scenario-driven 5-year DCF that reads `Investment_DD_Extended_DCF_NPV_v10_2.csv` and outputs per-scenario implied share price & margin of safety.
- `DCFModel_fixed.py` — a more robust DCFModel implementation with safer yfinance handling and fallbacks.

These files are added in `add/dcf-scenarios` and do not replace the existing `DCFModel.py`.

## Dependencies

Install with:

```bash
pip install -r requirements.txt
```

(Repository `requirements.txt` should include `numpy`, `pandas`, `yfinance`.)

## Usage examples

1. DCFModel_with_scenarios.py (reads your Investment DD CSV and runs scenarios):

```bash
python DCFModel_with_scenarios.py --ticker NVDA --dd_csv Investment_DD_Extended_DCF_NPV_v10_2.csv
```

Options:
- `--ticker`: ticker symbol (required)
- `--dd_csv`: path to Investment DD CSV (required)
- `--years`: projection years (default 5)
- `--use_csv_wacc`: if present, use WACC from CSV when available

2. DCFModel_fixed.py (robust single-ticker DCF implementation):

```bash
python DCFModel_fixed.py --ticker KO
```

Options:
- `--ticker`: ticker symbol (required)
- `--TGR`: terminal growth rate (default 0.03)
- `--riskfree`: risk-free ticker (default `^TNX`)
- `--market`: market ticker (default `VTI`)


## Notes & Caveats

- These are screen-grade tools. The DD CSV contains human-written shorthand (e.g., `+45-55% near term then +20-30%`) which the parser attempts to convert into per-year rates using pragmatic rules. Review parsed rates before making decisions.
- For companies with missing `sharesOutstanding`, per-share results will be invalid until you provide shares or fix the ticker data.
- Terminal value is calculated using a Gordon Perpetuity method; run sensitivity checks for WACC and terminal growth.

