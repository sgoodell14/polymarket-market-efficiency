# Data feasibility findings

Reviewed capture: `20260909T153138473505Z` (September 9, 2026, UTC).

**Verdict: the public APIs support a joined market-trade-wallet prototype. Complete historical coverage, a mutually exclusive category taxonomy, and defensible trader-performance estimates are not yet established.**

[Raw responses](../data/raw/20260909T153138473505Z/) | [Request manifest](../data/raw/20260909T153138473505Z/manifest.json) | [Selection rules](../data/raw/20260909T153138473505Z/selection.json) | [Market table](../data/clean/20260909T153138473505Z/markets.csv) | [Trade table](../data/clean/20260909T153138473505Z/trades.csv) | [Wallet trade table](../data/clean/20260909T153138473505Z/wallet_trades.csv) | [Wallet-category table](../data/clean/20260909T153138473505Z/wallet_category.csv) | [Quality report](../data/clean/20260909T153138473505Z/quality_report.json) | [Collector code](../src/prove_data.py) | [Cleaning code](../src/clean_data.py)

## What the live pull established

| Requested element | Evidence in the reviewed capture |
|---|---|
| A set of markets | 12 unique markets selected from Politics, Sports, and Crypto tags, including an older-listing stratum. |
| Resolved outcomes | 12 explicit resolved statuses with unique 0/1 outcome-price vectors. Named outcomes are preserved. Labels are from Gamma, not an independent on-chain resolution audit. |
| Market trade history | 1,178 retrieved trade rows; every condition ID and outcome token joins successfully. |
| Wallet IDs | 418 distinct proxy-wallet addresses in market trade rows. |
| One wallet's activity | 200 records: 188 TRADE, 8 REDEEM, 3 REWARD, and 1 MAKER_REBATE. All 188 TRADE records join to market metadata. |
| Category | Tags are available, but all 12 top-level category fields are missing; 3 selected markets have multiple recognized domains. |
| Time, price, size, side | Validated in all 1,178 market trade rows and all 188 wallet TRADE records. Side is BUY/SELL, separate from the outcome label. |

The raw collector makes public GET requests only. The reviewed run has no HTTP errors and no rejected trade rows.

## A real joined example

```yaml
MARKET:
  market_id: "3093334"
  question: "Will AfD win 50 or more seats in the 2026 Sachsen-Anhalt parliamentary elections?"
  category: "Politics"
  resolution: "No"
  forecast_outcome: "Yes"
  price_30_days_before_closure: 0.0465
  price_7_days_before_closure: 0.006
  price_1_day_before_closure: 0.0015
TRADE:
  wallet: "0x99f7df5c91f048d291c3759cd086ce670196f5ae"
  timestamp_utc: "2026-09-06T22:37:04+00:00"
  side: "BUY"
  outcome: "Yes"
  price: 0.001
  size_shares: 5.0
```

The wallet used for the separate activity proof is `0x7c9e0b03d7505dad7e87777cd282628f75b2db3d`, chosen as the most frequent wallet in the market-trade sample. Its 188 sampled trade records group as follows; combined labels remain a single category to avoid counting a record twice:

- Business;Technology: 2 trade records
- Climate: 2 trade records
- Crypto: 30 trade records
- Economy;Finance: 1 trade records
- Economy;Politics: 1 trade records
- Geopolitics: 4 trade records
- Geopolitics;Politics: 1 trade records
- Politics: 111 trade records
- Sports: 36 trade records

These are sample counts, not full wallet histories or evidence of skill. Public addresses do not identify unique people.

## Issues found now

1. **Gamma wallet joins need both market states.** The first attempt lost 65 wallet TRADE records because metadata retrieval defaulted to open markets. Fetching both `closed=false` and `closed=true` recovered all 188 joins in the reviewed capture. Earlier raw runs retain the failed experiment for comparison.
2. **Domain labels overlap.** Three markets sampled under Politics were also tagged Crypto. The prototype retains exact sorted tag combinations instead of imposing a primary category. A reviewed taxonomy or an explicit overlap-exclusion rule is necessary for domain-specific skill research.
3. **History remains bounded.** Each market has at most two 100-row pages. Four markets hit that cap; eight returned a short page. Wallet activity hit its 200-record cap. Neither a short page nor the API's reported lifetime volume independently establishes complete historical coverage.
4. **Most selected markets are too short-lived for long horizons.** Price availability is 1/12 at 30 days, 2/12 at 7 days, and 5/12 at 1 day. Every other target precedes the market's recorded startDate. A month-ahead study needs a different sampling frame.
5. **Price-window length matters.** The initial 32-day CLOB query returned HTTP 400: interval too long. Six-hour windows ending at the target horizons succeeded. The cleaner selects only observations at or before the target, retains timestamp and age, and permits at most six hours of staleness.
6. **Closure time is not a reliable substitute for the event-information cutoff.** Some closedTime values precede their scheduled endDate. Both are retained; these provisional price horizons are relative to closedTime. Event rules and information availability need review before calibration or forecast tests.
7. **Trade identity and performance need more work.** Five exact duplicate market-row candidates are retained because the API response lacks a unique fill/log index. The collector requests `takerOnly=false`; sampled notional is an aggregate of returned rows, not an independently reconciled economic volume. Positions, inventory, fees, redemptions, transfers, and full cash-flow histories are needed before computing profit or ROI. Those fields remain blank.

## Endpoint examples and documentation

The manifest contains exact fully parameterized requests and response hashes. Core patterns:

```text
https://gamma-api.polymarket.com/markets?closed=true&uma_resolution_status=resolved&include_tag=true&limit=3
https://data-api.polymarket.com/trades?market=<condition_id>&takerOnly=false&limit=100&offset=0
https://data-api.polymarket.com/activity?user=<proxy_wallet>&start=1&limit=100&sortBy=TIMESTAMP&sortDirection=DESC
https://gamma-api.polymarket.com/markets?condition_ids=<condition_id>&closed=true&include_tag=true
https://clob.polymarket.com/prices-history?market=<outcome_token_id>&startTs=<unix_seconds>&endTs=<unix_seconds>&fidelity=60
```

Official references checked September 9, 2026: [market filters](https://docs.polymarket.com/api-reference/markets/list-markets), [trade records and pagination](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets), [wallet activity](https://docs.polymarket.com/api-reference/core/get-user-activity), and [historical prices](https://docs.polymarket.com/api-reference/markets/get-prices-history). The documented trade and activity APIs support time windows; production collection should test window boundaries, caps, and repeated retrievals before claiming completeness.

## Validation and next step

Seven automated tests passed for conservative outcome labeling, named outcomes, category overlap, price timing and staleness, pre-listing missingness, trade validation/joins, and pagination coverage flags. The exploration notebook executed successfully against this captured run. Raw-response hashes were verified before cleaning, and raw-to-clean row references were checked.

Next, define a small cohort of markets that were open at least 30 days before a defensible event cutoff, establish complete trade coverage for that cohort, and review the category mapping. The current evidence supports continuing the project while leaving the skill hypothesis untested. The full website and assignment EDA remain tracked in the [assignment checklist](assignment_checklist.md).
