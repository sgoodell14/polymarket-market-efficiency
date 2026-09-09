"""Prepare reproducible pilot figures, page content, and linked website downloads."""
import csv
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN = "20260909T153138473505Z"
RAW = ROOT / "data/raw" / RUN
CLEAN = ROOT / "data/clean" / RUN
WEB = ROOT / "website"
ASSETS = WEB / "assets"
FIGURES = ROOT / "figures"
INK, TEAL, ORANGE, PALE = "#193149", "#076b78", "#b75b22", "#cad8e2"


def read_csv(name):
    with (CLEAN / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def save(fig, name):
    fig.savefig(FIGURES / name, dpi=170, bbox_inches="tight", facecolor="white")
    shutil.copy2(FIGURES / name, ASSETS / name)
    plt.close(fig)


def plot(title, subtitle=None, height=5):
    fig, ax = plt.subplots(figsize=(10.8, height))
    ax.set_title(title, loc="left", fontsize=17, fontweight="bold", color=INK, pad=28 if subtitle else 16)
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=10.5, color="#50667b")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=.15)
    ax.set_axisbelow(True)
    return fig, ax


def information_flow():
    from matplotlib.patches import FancyBboxPatch
    fig, ax = plt.subplots(figsize=(12, 3.1))
    fig.patch.set_facecolor("#eef5f8")
    ax.set_facecolor("#eef5f8")
    ax.axis("off")
    ax.set(xlim=(0, 12), ylim=(0, 3.1))
    boxes = [(.2, "INFORMATION", "Politics / Sports\nCrypto / Economy"),
             (3.2, "PARTICIPANTS", "Knowledge and beliefs\nexpressed through trades"),
             (6.2, "MARKET PRICE", "A changing forecast\n$0.65 implies about 65%"),
             (9.2, "RESOLVED OUTCOME", "Compare the forecast\nwith what occurred")]
    for x, title, body in boxes:
        ax.add_patch(FancyBboxPatch((x, .75), 2.55, 1.55,
            boxstyle="round,pad=0.05,rounding_size=0.06", facecolor="white", edgecolor="#b9ccd9", linewidth=1.2))
        ax.text(x + .14, 1.91, title, fontsize=9.5, fontweight="bold", color=TEAL)
        ax.text(x + .14, 1.18, body, fontsize=10.3, color=INK, linespacing=1.65)
    for x in [2.8, 5.8, 8.8]:
        ax.annotate("", xy=(x + .32, 1.5), xytext=(x, 1.5), arrowprops=dict(arrowstyle="->", color=TEAL, lw=1.7))
    ax.text(.2, .18, "A conceptual view of information aggregation. The 65% price is illustrative.", fontsize=10, color="#4e6377")
    save(fig, "information-flow.png")


def main():
    for path in (ASSETS, FIGURES, WEB / "downloads/clean", WEB / "downloads/code"):
        path.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK, "axes.edgecolor": PALE})
    markets, trades, wallets = read_csv("markets.csv"), read_csv("trades.csv"), read_csv("wallet_category.csv")
    report = json.loads((CLEAN / "quality_report.json").read_text(encoding="utf-8"))
    selection = json.loads((RAW / "selection.json").read_text(encoding="utf-8"))
    information_flow()
    pages = []

    def section(title, filename, caption, alt):
        pages.append(f"### {len(pages) + 1:02d} - {title}\n\n![{caption}](assets/{filename}){{fig-alt=\"{alt}\"}}\n")

    counts = Counter(m["category"] for m in markets)
    labels, values = zip(*sorted(counts.items(), key=lambda item: item[1]))
    fig, ax = plot("The pilot spans four domain-tag combinations", "12 selected markets - overlapping tags are retained", 3.9)
    bars = ax.barh(labels, values, color=TEAL, height=.58)
    ax.bar_label(bars, padding=7); ax.set_xlim(0, max(values) + 1); ax.set_xlabel("Selected markets")
    ax.xaxis.get_major_locator().set_params(integer=True)
    save(fig, "01-domain-composition.png")
    section("Market categories", "01-domain-composition.png", "Sports and Crypto account for the largest single-domain groups in this pilot. Three other markets carry both Crypto and Politics tags, so domain definitions need review before comparisons.", "Horizontal bars showing four Sports, four Crypto, three Crypto and Politics, and one Politics market.")

    from datetime import datetime
    def stamp(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    durations = {m["market_id"]: (stamp(m["closed_time_utc"]) - stamp(m["start_date_utc"])) / 86400 for m in markets}
    ordered = sorted(markets, key=lambda m: durations[m["market_id"]])
    fig, ax = plot("Most sampled markets were open for only a few days", "Time from recorded startDate to closedTime - these are metadata proxies", 6)
    vals = [durations[m["market_id"]] for m in ordered]
    ax.barh([m["market_id"] for m in ordered], vals, color=TEAL, height=.62)
    ax.axvline(30, color=ORANGE, ls="--", lw=1.3, label="30-day horizon")
    ax.set_xlabel("Recorded market lifetime (days)"); ax.set_ylabel("Market ID"); ax.legend(frameon=False)
    save(fig, "02-market-lifetime.png")
    section("Market duration", "02-market-lifetime.png", "Only one selected market spans a full 30-day pre-closure horizon. A study of month-ahead forecasts needs a sample designed around longer market lifetimes.", "Market lifetimes in days with a reference line at 30 days.")

    ordered = sorted(markets, key=lambda m: float(m["total_volume_reported"]))
    fig, ax = plot("Reported volume varies substantially across markets", "Platform-reported totals - logarithmic scale", 6)
    ax.barh([m["market_id"] for m in ordered], [float(m["total_volume_reported"]) for m in ordered], color=TEAL, height=.62)
    ax.set_xscale("log"); ax.set_xlabel("Reported market volume (log scale)"); ax.set_ylabel("Market ID")
    save(fig, "03-reported-volume.png")
    section("Reported trading volume", "03-reported-volume.png", "The selected markets differ substantially in platform-reported trading volume. These totals describe the platform's market summaries and should be kept separate from notional amounts summed over the sampled trade rows.", "Horizontal bar chart of platform-reported volume for each market on a logarithmic scale.")

    ordered = sorted(markets, key=lambda m: int(m["sample_trade_rows"]))
    fig, ax = plot("Four markets reached the 200-row collection limit", "Orange bars stopped at the pilot cap; teal bars returned a short page", 6)
    colors = [ORANGE if m["trade_stop_reason"] == "sample_cap" else TEAL for m in ordered]
    ax.barh([m["market_id"] for m in ordered], [int(m["sample_trade_rows"]) for m in ordered], color=colors, height=.62)
    ax.axvline(200, color=ORANGE, ls="--", lw=1); ax.set_xlabel("Retrieved trade rows"); ax.set_ylabel("Market ID")
    save(fig, "04-trade-coverage.png")
    section("Trade-history coverage", "04-trade-coverage.png", "Four markets reached the deliberately imposed 200-row cap. A shorter response establishes the size of the returned sample but does not independently verify complete trading history.", "Trade-row counts by market, with four markets marked at the 200-row collection cap.")

    ordered = sorted(markets, key=lambda m: int(m["sample_number_traders"]))
    fig, ax = plot("Observed participation differs across the sampled markets", "Distinct proxy-wallet addresses in the retrieved trade rows", 6)
    ax.barh([m["market_id"] for m in ordered], [int(m["sample_number_traders"]) for m in ordered], color=TEAL, height=.62)
    ax.set_xlabel("Distinct observed wallets"); ax.set_ylabel("Market ID")
    save(fig, "05-observed-wallets.png")
    section("Observed participation", "05-observed-wallets.png", "The sample reveals differences in the number of wallet addresses observed trading each market. The counts depend on retrieved history, and wallet addresses do not identify distinct people.", "Horizontal bars comparing distinct observed wallet addresses for the twelve sampled markets.")

    ordered = sorted(markets, key=lambda m: float(m["sample_trader_concentration_hhi"]))
    fig, ax = plot("Sample trading concentration is uneven", "HHI: sum of squared wallet shares of retrieved trade notional", 6)
    ax.barh([m["market_id"] for m in ordered], [float(m["sample_trader_concentration_hhi"]) for m in ordered], color=TEAL, height=.62)
    ax.set_xlim(0, 1); ax.set_xlabel("Sample concentration (HHI; higher means more concentrated)"); ax.set_ylabel("Market ID")
    save(fig, "06-concentration.png")
    section("Trading concentration", "06-concentration.png", "Higher HHI values indicate that fewer wallets account for a larger share of the retrieved trade notional. Very small or capped samples can distort this measure, so the chart does not establish a relationship with forecast accuracy.", "Sample wallet-notional concentration for each market on a zero-to-one HHI scale.")

    fig, ax = plot("Price coverage improves at shorter forecast horizons", "Most missing targets predate the selected market's recorded start", 3.8)
    horizon = ["30 days", "7 days", "1 day"]; available = [1, 2, 5]; missing = [11, 10, 7]
    ax.barh(horizon, available, color=TEAL, label="Price available", height=.55)
    ax.barh(horizon, missing, left=available, color=PALE, label="Market not yet open", height=.55)
    for i, (a, b) in enumerate(zip(available, missing)):
        ax.text(a / 2, i, str(a), va="center", ha="center", color="white", fontweight="bold")
        ax.text(a + b / 2, i, str(b), va="center", ha="center", color=INK)
    ax.set_xlim(0, 12); ax.set_xlabel("Markets"); ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(.5, -.23), ncol=2)
    save(fig, "07-price-coverage.png")
    section("Historical price availability", "07-price-coverage.png", "Prices are available for one market at 30 days, two at seven days, and five at one day before recorded closure. The remaining targets precede market opening rather than indicating a failed price request in the reviewed run.", "Stacked bars show available prices for one, two, and five of twelve markets at the 30-day, seven-day, and one-day horizons.")

    sizes = np.array([float(t["size_shares"]) for t in trades])
    fig, ax = plot("Trade sizes span several orders of magnitude", "1,178 retrieved market trade rows - five duplicate candidates retained", 4.7)
    ax.hist(sizes, bins=np.geomspace(sizes.min(), sizes.max(), 26), color=TEAL, edgecolor="white", linewidth=.5)
    ax.set_xscale("log"); ax.set_xlabel("Outcome shares per trade row (log scale)"); ax.set_ylabel("Trade rows"); ax.grid(axis="y", alpha=.15)
    save(fig, "08-trade-sizes.png")
    section("Trade-size distribution", "08-trade-sizes.png", "The retrieved trade quantities span a wide range, making a logarithmic horizontal scale useful. Size is measured in outcome shares; the cash notional of a trade also depends on its price.", "Histogram of outcome-share quantities across 1,178 retrieved trade rows on a logarithmic horizontal scale.")

    fig, ax = plot("Sampled trade prices cluster near outcome extremes", "Prices refer to the traded outcome, which can be Yes, No, or a named result", 4.7)
    ax.hist([float(t["price"]) for t in trades], bins=np.linspace(0, 1, 21), color=TEAL, edgecolor="white", linewidth=.5)
    ax.set_xlim(0, 1); ax.set_xlabel("Price per outcome share"); ax.set_ylabel("Trade rows"); ax.grid(axis="y", alpha=.15)
    save(fig, "09-trade-prices.png")
    section("Trade-price distribution", "09-trade-prices.png", "Many retrieved rows have prices close to zero or one, consistent with this sample emphasizing late trading in resolved markets. This pooled distribution combines different outcomes and observation times, so it is not a calibration curve.", "Histogram of sampled trade prices between zero and one, pooled across traded outcome tokens.")

    ordered = sorted(wallets, key=lambda r: int(r["sample_num_trades"]))
    fig, ax = plot("One sampled wallet trades across multiple domains", "188 joined TRADE activity records - combined tags remain one category", 5.4)
    bars = ax.barh([r["category"].replace(";", " + ") for r in ordered], [int(r["sample_num_trades"]) for r in ordered], color=TEAL, height=.6)
    ax.bar_label(bars, padding=5); ax.set_xlim(0, 125); ax.set_xlabel("Sampled trade records")
    save(fig, "10-wallet-domains.png")
    section("One wallet across domains", "10-wallet-domains.png", "Politics accounts for the largest share of this wallet's sampled activity, with Sports and Crypto also represented. The pattern demonstrates that cross-domain histories can be joined, but it does not establish specialization, profitability, or forecasting skill.", "Nine domain-tag combinations for one wallet, led by 111 Politics, 36 Sports, and 30 Crypto trade records.")

    sample = trades[:3]
    first_source = json.loads((RAW / sample[0]["source_file"]).read_text(encoding="utf-8"))[int(sample[0]["source_row"])]
    excerpt = {k: first_source[k] for k in ["conditionId", "proxyWallet", "timestamp", "side", "outcome", "price", "size"]}
    fig = plt.figure(figsize=(11, 3.1)); fig.text(.02, .90, "Raw API record - selected fields", fontsize=16, fontweight="bold", color=INK)
    fig.text(.02, .74, json.dumps(excerpt, indent=2), family="DejaVu Sans Mono", fontsize=10, va="top", color=INK)
    save(fig, "raw-data-example.png")
    fig, ax = plt.subplots(figsize=(11, 2.2)); ax.axis("off"); ax.set_title("Cleaned trade rows - selected fields", loc="left", fontsize=16, color=INK, pad=12)
    columns = ["market_id", "side", "outcome", "price", "size_shares", "notional_usdc"]
    cells = [[r[c] if c not in ["price", "size_shares", "notional_usdc"] else f"{float(r[c]):,.4g}" for c in columns] for r in sample]
    table = ax.table(cellText=cells, colLabels=columns, loc="center", cellLoc="left", colLoc="left")
    table.auto_set_font_size(False); table.set_fontsize(10); table.scale(1, 1.9)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(PALE)
        if r == 0: cell.set_facecolor("#eaf3f6"); cell.set_text_props(weight="bold", color=INK)
    save(fig, "clean-data-example.png")

    for path in CLEAN.iterdir():
        if path.is_file(): shutil.copy2(path, WEB / "downloads/clean" / path.name)
    shutil.copy2(ROOT / "docs/data_dictionary.md", WEB / "downloads/data_dictionary.md")
    shutil.copy2(ROOT / "docs/data_feasibility.md", WEB / "downloads/data_feasibility.md")
    shutil.copy2(ROOT / "notebooks/01_data_exploration.ipynb", WEB / "downloads/01_data_exploration.ipynb")
    source_files = sorted((ROOT / "src").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    for path in source_files: shutil.copy2(path, WEB / "downloads/code" / path.name)
    with zipfile.ZipFile(WEB / "downloads/raw-sample.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(RAW.iterdir()):
            if path.is_file(): archive.write(path, arcname=f"{RUN}/{path.name}")
    shutil.copy2(RAW / "manifest.json", WEB / "downloads/raw-manifest.json")
    with zipfile.ZipFile(WEB / "downloads/source-code.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files: archive.write(path, arcname=str(path.relative_to(ROOT)))
        archive.write(ROOT / "requirements.txt", "requirements.txt")
        archive.write(ROOT / "requirements-website.txt", "requirements-website.txt")
        for pattern in ("*.qmd", "*.yml", "*.scss"):
            for path in sorted(WEB.glob(pattern)):
                archive.write(path, arcname=str(path.relative_to(ROOT)))

    market_table = "\n".join(f"| {m['market_id']} | {m['question'].replace('|', '/')} | {m['category'].replace(';', ' + ')} | {m['resolution']} |" for m in markets)
    joined_pages = "\n".join(pages)
    content = f"""---
title: "Data Preparation & EDA"
subtitle: "A small pilot establishes the raw material for the research."
---

::: {{.eyebrow}}
DataPrep_EDA - Capture: 9 September 2026 UTC
:::

The pilot tests whether public Polymarket records can support a study of information aggregation. It combines market metadata, resolved outcome labels, trade records, and one wallet's activity. The saved capture is fixed, so every figure on this page can be reproduced without making new API requests.

<div class="metric-strip">
<div><span class="value">12</span><span class="label">resolved markets</span></div>
<div><span class="value">1,178</span><span class="label">market trade rows</span></div>
<div><span class="value">418</span><span class="label">observed wallet addresses</span></div>
<div><span class="value">188</span><span class="label">joined wallet trade records</span></div>
</div>

::: {{.callout-note title="How to read this pilot"}}
These are descriptive results from a small, deliberately bounded sample. They establish data availability and reveal collection issues; they do not estimate overall market efficiency or trader skill. All 188 TRADE records in the selected wallet's 200 activity records joined successfully, while the other 12 records describe redemptions, rewards, and a maker rebate.
:::

## Sources and collection

The collector selected three recent resolved markets per Politics, Sports, and Crypto tag, plus one older listing per tag. Discovery required platform-reported volume of at least 1,000. The older-listing filter used a start date at least 45 days before the capture and a scheduled end date within the preceding 30 days or later; actual lifetimes still require inspection because closure can precede the scheduled end.

Each market was limited to two pages of 100 trade records. The selected wallet was the most frequently observed wallet in those sampled rows; its latest 200 activity records were retrieved with a fixed upper time bound. This selection favors recent activity and frequent observed participants.

| Source | What it contributes | Documentation |
|---|---|---|
| Gamma API | Market questions, IDs, tags, outcome tokens, resolution status, reported volume | [Markets](https://docs.polymarket.com/api-reference/markets/list-markets) |
| Data API | Public wallet addresses, BUY/SELL sides, prices, share quantities, and timestamps | [Trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets) |
| Data API | Trades and other activity for one public proxy wallet | [Wallet activity](https://docs.polymarket.com/api-reference/core/get-user-activity) |
| CLOB API | Historical prices for an outcome token | [Price history](https://docs.polymarket.com/api-reference/markets/get-prices-history) |

A concrete metadata request used in this workflow is:

```text
https://gamma-api.polymarket.com/markets?tag_id=2&closed=true&uma_resolution_status=resolved&volume_num_min=1000&limit=3&order=id&ascending=false&include_tag=true
```

A trade-history request identifies a market by its condition ID:

```text
https://data-api.polymarket.com/trades?market=0x1d8f9398b0412678865cfc50aea7d49025b35e54a8a4fe1a223db45447e4138a&takerOnly=false&limit=100&offset=0
```

The [request manifest](downloads/raw-manifest.json) records the exact captured URLs, times, HTTP status codes, and response hashes. [Collection code](downloads/code/prove_data.py) and [the full raw capture](downloads/raw-sample.zip) are available for inspection.

## Raw records to analytical tables

Market records join to trades through `conditionId`. Outcome token IDs and their ordered outcome labels provide a second consistency check. Gamma metadata must be fetched for both open and closed markets when joining wallet activity; querying only open markets initially omitted 65 wallet trade records.

The cleaner validates wallet addresses, condition and token joins, outcome labels, BUY/SELL sides, positive quantities, prices between zero and one, and timestamps no later than the capture cutoff. Resolved labels require an explicit resolved status and a unique 0/1 outcome-price vector. The reviewed run has no rejected trade rows.

![The raw response preserves API field names and the original values. This image shows selected fields from one saved record; the downloadable raw capture contains the complete responses.](assets/raw-data-example.png){{fig-alt="Selected raw JSON fields showing a condition ID, wallet address, timestamp, trade side, outcome, price, and share size."}}

![The cleaned table gives fields consistent analytical names and adds trade notional as price multiplied by shares. These three displayed records remain traceable to their source files and row numbers in the downloadable trade table.](assets/clean-data-example.png){{fig-alt="Three cleaned trade rows showing market ID, side, outcome, price, share size, and computed notional."}}

Category labels use exact recognized tag slugs; overlapping domains remain combined. All 12 top-level category fields are absent, but their tags allow provisional classification. Five exact duplicate market-row candidates are retained because the response lacks a unique fill identifier, so identical observed rows cannot safely distinguish duplicate delivery from separate fills.

Missing values stay missing with an explicit reason. Wallet profit, win rate, and ROI remain unestimated because the bounded sample does not reconstruct full positions or cash flows. Valid extreme trade sizes are retained. [Cleaning code](downloads/code/clean_data.py) and [field definitions](downloads/data_dictionary.md) document the transformations.

## Explore the pilot

Figures use only the reviewed capture. Market IDs can be matched to the questions in the market register below. All figure-generation code is available in [prepare_website.py](downloads/code/prepare_website.py).

{joined_pages}

## What these checks change

- **Historical coverage:** Four markets and the selected wallet hit the collection cap. More complete collection and independent coverage checks are needed before interpreting lifetime participation or performance.
- **Forecast horizons:** Most sampled markets are too short-lived for a 30-day comparison. A longer-running cohort must be selected deliberately.
- **Price timing:** Six-hour requests around the chosen historical targets succeeded after a larger 32-day request failed. Prices are taken only at or before each target and at most six hours earlier; timestamp and age remain in the table.
- **Event timing:** Scheduled end dates and closure times can differ. A defensible information cutoff needs review before forecast evaluation.
- **Domain definitions:** Multiple tags and unclassified subjects require a reviewed taxonomy before cross-domain skill comparisons.

## Market register

| Market ID | Question | Domain tags | Resolved label |
|---|---|---|---|
{market_table}

## Data and code

All linked tables refer to capture `{RUN}`. Public raw API responses include wallet addresses and profile fields; the cleaned analytical tables omit profile names, biographies, and images.

| Artifact | Download |
|---|---|
| Exact raw responses and collection metadata | [Raw sample ZIP](downloads/raw-sample.zip) / [Manifest JSON](downloads/raw-manifest.json) |
| One row per market | [markets.csv](downloads/clean/markets.csv) |
| Retrieved market trade rows | [trades.csv](downloads/clean/trades.csv) |
| Selected wallet's joined trades | [wallet_trades.csv](downloads/clean/wallet_trades.csv) |
| One row per wallet by domain-tag combination | [wallet_category.csv](downloads/clean/wallet_category.csv) |
| Validation counts and missingness | [quality_report.json](downloads/clean/quality_report.json) |
| Reproducible collector, cleaner, figure scripts, and tests | [Source code ZIP](downloads/source-code.zip) |
| Executed data inspection notebook | [01_data_exploration.ipynb](downloads/01_data_exploration.ipynb) |
| Field definitions and assumptions | [Data dictionary](downloads/data_dictionary.md) |

A complementary source, a larger research sample, and the later course analyses remain to be developed. [Current conclusions](Conclusions.qmd) distinguish the established data joins from the research questions still open.
"""
    (WEB / "DataPrep_EDA.qmd").write_text(content, encoding="utf-8", newline="\n")
    print(f"Prepared 10 pilot figures, raw/clean examples, and downloads from {RUN}.")


if __name__ == "__main__":
    main()
