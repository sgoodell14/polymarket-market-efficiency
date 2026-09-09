# Polymarket Market Efficiency

**Topic:** Information Discovery and Market Efficiency in Prediction Markets

**Broad question:** What characteristics make prediction markets effective at aggregating information?

**Areas of interest:** market calibration, trader specialization, trader skill, liquidity, participation, concentration, information discovery, and whether transaction-level information adds predictive value beyond the current market probability.

The central skill question is: **Is forecasting skill general, or is it domain-specific?** The first stage establishes whether markets, resolution labels, trade records, and wallet activity can be joined. Research questions and the full course website follow the data feasibility check.

## Run the first-stage pipeline

Python 3.11 or newer; the collector and cleaner use the standard library. No API key or wallet connection is needed. Run from this repository:

```powershell
python src/prove_data.py
python src/clean_data.py
python -m unittest discover -s tests -v
```

Each pull creates a dated folder under `data/raw/`. The cleaner selects the latest completed capture, or accepts `--run data/raw/<run-id>`, and writes matching CSVs under `data/clean/<run-id>/`. A rerun makes a new live sample; offline cleaning of a specific run is reproducible. All timestamps use UTC.

Read [the feasibility findings](docs/data_feasibility.md), [data dictionary](docs/data_dictionary.md), and [remaining assignment requirements](docs/assignment_checklist.md).

## Project structure

```text
README.md
src/
  prove_data.py             # Small public API collector: markets + trades + wallet
  clean_data.py             # Offline validation and prototype tables
notebooks/
  01_data_exploration.ipynb # Inspect the captured sample and its limitations
data/                      # Raw responses and clean tables, separated by run
  raw/
  clean/
docs/                      # Findings, field definitions, assignment checklist
figures/                   # Reproducible pilot figures and data examples
website/                   # Quarto source, course pages, and linked downloads
tests/                     # Resolution, joins, and historical-price checks
```

The collector stays in one script for the first proof; `get_markets.py` and `get_trades.py` can be extracted when collection grows.

## What the prototype means

`markets.csv` contains one row per sampled market. `trades.csv` keeps wallet, condition ID, outcome token, BUY/SELL side, outcome label, time, price, shares, and notional value. `wallet_trades.csv` links the selected wallet's TRADE activity to market tags. `wallet_category.csv` groups those records by wallet and exact domain-tag combination.

The sample is deliberately small and nonrepresentative. Market statistics prefixed `sample_` describe retrieved rows, not lifetime market totals. Wallets are addresses, not identified people. Profit, win rate, and ROI remain blank because incomplete positions, costs, and activity cannot support those claims. Missing historical prices stay missing with an explicit reason.

## Data sources

- [Gamma market metadata](https://docs.polymarket.com/api-reference/markets/list-markets): questions, condition IDs, tokens, tags, resolution status, and reported volume.
- [Data API trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets): public wallet-level trade records.
- [Data API activity](https://docs.polymarket.com/api-reference/core/get-user-activity): trades and other wallet activity.
- [CLOB historical prices](https://docs.polymarket.com/api-reference/markets/get-prices-history): token price observations.

Raw response bodies are preserved unchanged. Each run's `manifest.json` records request URLs, retrieval times, HTTP status, and SHA-256 hashes. CSV rows point back to raw files and zero-based source row numbers.

## Course website

The Quarto website now contains the Introduction, ten provisional research questions, DataPrep_EDA with ten descriptive pilot figures, and all required later-module pages. The later analyses remain explicitly pending. A private Sites deployment is used for review; the static output remains compatible with GitHub Pages.

Edit `website/index.qmd` for the introduction, `_quarto.yml` for navigation, and `theme.scss` for styling. `src/prepare_website.py` generates the DataPrep_EDA page, figures, and downloads from the fixed reviewed capture; edit that script to change generated content.

```powershell
python -m pip install -r requirements-website.txt
python src/build_website.py
```

The build uses portable Quarto 1.9.38 from `.tools/bin/quarto.exe`, or Quarto on PATH. Local preview: `.\.tools\bin\quarto.exe preview website`. The final build renders a staging copy under `.artifacts/` and puts portable output in root `dist/` for hosting; the live preview uses `website/dist/`. All generated output and the local Quarto installation are ignored by Git.

Private review URL: https://polymarket-market-efficiency.arcane-koi-3804.chatgpt.site

The course submission still needs a public URL, a complementary data source, and a larger justified analytical sample. No GitHub repository has been created.
