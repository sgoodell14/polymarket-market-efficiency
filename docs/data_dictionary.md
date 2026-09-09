# Prototype data dictionary

Blank CSV cells mean unavailable or not estimable, never zero. Raw JSON retains original names and types. CSV readers should read IDs, wallet addresses, and token IDs as strings. Files under `data/clean/<run-id>/` are reproducible with `src/clean_data.py`.

## Market table

| Field | Definition |
|---|---|
| `market_id` | Gamma market ID, stored as text; not the event ID. |
| `condition_id` | Join key between Gamma markets and Data API trades/activity. |
| `category` | Sorted semicolon-separated domain labels from exact tag slugs. Multiple labels remain together; absent recognized tags become `Unclassified`. |
| `category_source`, `raw_category`, `tag_slugs` | Transformation rule and preserved category/tag evidence. The version-1 mapping is in `DOMAINS` in the cleaner. |
| `resolution` | Winning outcome label only when `closed=true`, `umaResolutionStatus=resolved`, and the prices are exactly one 1 and otherwise 0. Other resolutions remain unverified. |
| `resolution_source` | Evidence rule, not an independently verified on-chain payout. |
| `forecast_outcome` | First outcome token; may be Yes, a team, Over, or another label. |
| `final_outcome` | 1 if `forecast_outcome` won, 0 if another outcome won, blank if unverified. |
| `start_date_utc` | Gamma's startDate; a listing/opening proxy. |
| `scheduled_end_date_utc` | Gamma endDate, which can differ from actual closure. |
| `closed_time_utc` | Gamma closedTime; the explicit anchor used for provisional price horizons. Not a verified event-information cutoff. |
| `total_volume_reported` | Gamma volumeNum (fallback volume); a platform aggregate distinct from sampled row notional. |
| `sample_trade_rows` | Count of valid retrieved trade rows; may include duplicate candidates. |
| `sample_number_traders` | Distinct proxy-wallet addresses in those rows; not distinct people. |
| `sample_volume_usdc` | Sum(price * size) across sampled rows. With takerOnly=false, do not assume one row per economic match or compare directly with lifetime volume. |
| `sample_trader_concentration_hhi` | Sum of squared wallet shares of sample notional, from 0 to 1. |
| `sample_avg_trade_size_shares`, `sample_largest_trade_shares` | Mean and maximum token quantity, not dollar values. |
| `sample_first_trade_utc`, `sample_last_trade_utc` | Observed time span; not verified lifetime coverage. |
| `trade_stop_reason` | `sample_cap`, `short_page`, or `request_failed`. A short page is not independent evidence of complete history. |
| `full_trade_history_verified` | False in this prototype. |
| `price_{30,7,1}_days_before` | Last available first-outcome token price at or before closedTime minus the horizon, at most six hours stale. |
| `price_{30,7,1}d_observed_at_utc`, `...age_seconds` | Exact observation timestamp and age relative to target time. No forward observations or interpolation. |
| `price_{30,7,1}d_status` | Available, market not open at target, missing anchor, not retrieved/request failed, or no observation in the six-hour window. |

## Trade tables

`side` is BUY/SELL; `outcome` is the proposition or named result being traded. `price` is the price per outcome share; `size_shares` is quantity. `notional_usdc = price * size_shares` excludes fees and rebates. `asset_id` joins to the ordered `clobTokenIds` list and must agree with `outcome_index` and `outcome`. `timestamp` is Unix seconds; `timestamp_utc` is its readable form.

`source_file` and `source_row` identify the original response and zero-based row. `transaction_hash` is not a unique fill ID: a transaction can contain multiple records. Duplicate candidates are counted and retained because identical observable rows cannot safely distinguish repeated fills from duplicated responses. Invalid rows are recorded in `quality_report.json` with their reason.

## Wallet by category table

`sample_num_trades` counts joined TRADE records. `sample_num_buy_trades` counts BUY fills, not independent bets. `sample_num_markets` counts distinct condition IDs. `sample_volume_usdc` counts both buys and sells. `sample_avg_entry_probability` is the share-weighted entry price among BUY rows, across each purchased outcome; it is not a forecasting score.

Categories use exact tag combinations so a Crypto;Politics trade is counted once in that combined category, not twice. This is a provisional taxonomy and needs review before any cross-domain skill study. `profit`, `win_rate`, and `roi` are intentionally blank, with a `performance_status` reason. `full_wallet_history_verified` is false.

## Integrity and analytical limitations

The cleaner checks raw-response hashes, wallet format, condition and asset joins, outcome/index agreement, valid BUY/SELL sides, finite positive sizes, prices in [0,1], and positive timestamps no later than the capture cutoff. Extreme but valid trade sizes remain. Missingness is retained and explained rather than replaced with invented data.

Resolution labels, full-life volume, and final trade aggregates are future information relative to a forecast date. A modeling dataset must rebuild features using only information available before a defined cutoff and use time-aware evaluation. The current tables are a data feasibility prototype, not model-ready training data.
