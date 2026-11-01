"""Offline, non-mutating EDA audit of the effective research-cohort captures.

Run from any directory: python -B src/audit_eda_tables.py
Outputs are diagnostics, not cleaned tables. No API calls or automatic row drops.
"""
import csv
import gzip
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/cohort_audit/20260914_sample200"
OUT = BASE / "eda_audit_20260916_v2"
HEX40 = re.compile(r"0x[0-9a-fA-F]{40}\Z")
HEX64 = re.compile(r"0x[0-9a-fA-F]{64}\Z")
CORE = ("proxyWallet", "side", "asset", "conditionId", "size", "price",
        "timestamp", "outcome", "outcomeIndex", "transactionHash")


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def integer_time(value):
    return finite_number(value) and value > 0 and value == int(value)


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def effective_cutoff(anchor):
    """The collector sends integer epoch seconds; floor a positive UTC instant."""
    return math.floor(stamp(anchor)) - 86400


def numeric_key(value):
    return format(Decimal(str(value)).normalize(), "f") if finite_number(value) else str(value)


def economic_key(row):
    """Diagnostic candidate key; not a claim to identify an exchange fill."""
    return (str(row.get("proxyWallet", "")).lower(), row.get("side"),
            str(row.get("asset", "")), str(row.get("conditionId", "")).lower(),
            numeric_key(row.get("size")), numeric_key(row.get("price")),
            row.get("timestamp"), str(row.get("transactionHash", "")).lower())


def distribution(values):
    values = sorted(v for v in values if finite_number(v))
    if not values:
        return {"n": 0}
    def quantile(q):
        at = (len(values) - 1) * q
        lo, hi = math.floor(at), math.ceil(at)
        return values[lo] + (values[hi] - values[lo]) * (at - lo)
    return dict(n=len(values), min=values[0], p25=quantile(.25), median=quantile(.5),
                p75=quantile(.75), p90=quantile(.9), p95=quantile(.95),
                p99=quantile(.99), max=values[-1])


class Audit:
    def __init__(self):
        self.inputs = {}
        self.profile = defaultdict(lambda: {"rows": 0, "fields": defaultdict(
            lambda: {"present": 0, "blank": 0, "types": Counter()})})
        self.issues = []
        self.counts = Counter()

    def read(self, path):
        data = path.read_bytes()
        self.inputs[path.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
        return gzip.decompress(data) if path.suffix == ".gz" else data

    def json(self, path):
        return json.loads(self.read(path))

    def csv(self, path, table):
        rows = list(csv.DictReader(io.StringIO(self.read(path).decode("utf-8-sig"))))
        for row in rows:
            self.observe(table, row)
        return rows

    def observe(self, table, row):
        p = self.profile[table]
        p["rows"] += 1
        for field, value in row.items():
            f = p["fields"][field]
            f["present"] += 1
            f["blank"] += value is None or value == ""
            f["types"][type(value).__name__] += 1

    def check(self, ok, code, mid, table="markets", index="", detail="", severity="error"):
        if not ok:
            self.counts[code] += 1
            self.issues.append(dict(market_id=mid, table=table, source_row_index=index,
                                    issue=code, severity=severity, detail=detail))


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    a = Audit()
    candidates = a.csv(BASE / "active_candidates.csv", "candidate_metadata")
    sources = {
        "coverage": a.csv(BASE / "active_cohort_coverage.csv", "coverage_metadata"),
        "register": a.csv(BASE / "full_audit_20260915/cohort_audit_register.csv", "audit_register"),
        "forecasts": a.csv(BASE / "full_audit_20260915/checked_forecasts.csv", "checked_forecasts"),
        "options": a.csv(BASE / "active_market_options.csv", "option_metadata"),
    }
    ids = [r["market_id"] for r in candidates]
    a.check(len(ids) == len(set(ids)), "duplicate_market_id", "cohort")
    for name, rows in sources.items():
        other = [r["market_id"] for r in rows]
        a.check(len(other) == len(set(other)) and set(ids) == set(other), "membership_" + name, "cohort")
    views = {name: {r["market_id"]: r for r in rows} for name, rows in sources.items()}
    correction = a.json(BASE / "corrections/active_corrections.json")
    membership = a.json(BASE / "cohort_membership.json")
    a.check(set(ids) == set(membership["active_market_ids"]) and len(ids) == membership["active_count"],
            "approved_membership_join", "cohort")
    a.inputs[Path(__file__).relative_to(ROOT).as_posix()] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    per_market, duplicates = [], []
    value_lists, topic_values = defaultdict(list), defaultdict(lambda: defaultdict(list))
    tx_rows, tx_keys, tx_markets = Counter(), defaultdict(set), defaultdict(set)
    wallet_spellings, wallet_profiles = defaultdict(set), defaultdict(set)
    conditions, tokens_seen = defaultdict(set), defaultdict(set)
    totals, trade_categories, market_categories = Counter(), Counter(), defaultdict(Counter)
    tx_pair_patterns = Counter()
    large_rows = []
    for ordinal, candidate in enumerate(candidates, 1):
        mid, topic = candidate["market_id"], candidate["topic"]
        reg, coverage, options = (views[name][mid] for name in ("register", "coverage", "options"))
        folder = (BASE / coverage["capture_path"]).parent
        expected_base = BASE / "corrections" / correction[mid] if mid in correction else BASE
        a.check(folder.resolve() == (expected_base / "pilot_collection" / mid).resolve(), "effective_capture_path", mid)
        result = a.json(folder / "result.json")
        market = a.json(folder / "market.json.gz")
        trades = a.json(folder / "trades_window.json.gz")
        prices = a.json(folder / "prices_window.json.gz")
        raw_prices = a.json(folder / "prices_hourly.json.gz")["history"]
        request = a.json(folder / "prices_hourly.request.json")
        params = parse_qs(urlparse(request["url"]).query)
        outcomes = json.loads(market["outcomes"])
        tokens = json.loads(market["clobTokenIds"])
        outcome_prices = list(map(float, json.loads(market["outcomePrices"])))
        a.observe("saved_market_metadata", market)
        conditions[candidate["condition_id"]].add(mid)
        for token in tokens:
            tokens_seen[token].add(mid)
        lo, hi = result["window_start_timestamp"], result["cutoff_timestamp"]
        for key in ("market_id", "question", "condition_id", "first_token_id", "start_date", "event_family_id"):
            a.check(bool(candidate[key]), "missing_market_" + key, mid)
        a.check(str(market["id"]) == mid == result["market_id"], "market_id_join", mid)
        a.check(market["conditionId"] == candidate["condition_id"], "condition_join", mid)
        a.check(len(tokens) == len(outcomes) == len(outcome_prices) == 2, "binary_shape", mid)
        a.check(tokens[0] == candidate["first_token_id"], "first_token_join", mid)
        a.check(market["closed"] and sorted(outcome_prices) == [0, 1], "non_binary_resolution", mid)
        a.check(float(candidate["final_outcome"]) == outcome_prices[0] == float(reg["expected_outcome"]), "outcome_label_join", mid)
        a.check(params.get("market") == [tokens[0]] and params.get("fidelity") == ["60"], "price_request_token_or_fidelity", mid)
        a.check(hi == math.floor(stamp(reg["reviewed_cutoff_utc"])) == effective_cutoff(reg["reviewed_anchor_utc"]),
                "reviewed_cutoff_join", mid)
        a.check(lo == max(hi - 7 * 86400, math.ceil(stamp(candidate["start_date"]))), "window_start", mid)
        a.check(math.floor(stamp(options["forecast_cutoff"])) == hi and options["event_family_id"] == reg["event_family_id"], "option_metadata_join", mid)
        a.check(candidate["event_family_id"] == reg["event_family_id"], "candidate_family_join", mid)
        a.check(int(coverage["trade_rows"]) == result["trade_rows"] == len(trades) == int(reg["trade_rows"]), "trade_count_reconciliation", mid)
        a.check(int(coverage["price_points"]) == result["price_points"] == len(prices), "price_count_reconciliation", mid)
        a.check(reg["forecast_ready"] == "True" and result["trade_status"] == "api_window_exhausted", "collection_status", mid)
        a.check(stamp("2025-09-01T00:00:00Z") <= stamp(reg["reviewed_anchor_utc"]) < stamp("2026-09-01T00:00:00Z"), "event_outside_study_window", mid)
        a.check(stamp(candidate["closed_time"]) > hi, "closed_before_forecast", mid)
        if candidate["reported_volume"]:
            try:
                volume = float(candidate["reported_volume"])
                valid_volume = math.isfinite(volume) and volume >= 0
            except ValueError:
                valid_volume = False
            a.check(valid_volume, "invalid_reported_volume", mid)
        market_categories["topic"][topic] += 1
        market_categories["evidence_status"][reg["evidence_status"]] += 1
        market_categories["option_count_status"][options["option_count_status"]] += 1
        market_categories["first_outcome_name"][outcomes[0] if outcomes[0] in ("Yes", "No") else "named competitor"] += 1
        market_categories["event_month"][reg["reviewed_anchor_utc"][:7]] += 1
        market_categories["label"][str(int(outcome_prices[0]))] += 1
        exact, economic = defaultdict(list), defaultdict(list)
        wallets, wallet_raw = set(), set()
        times, notionals, sizes, tprices = [], [], [], []
        bad_trade_rows, edge_trades = set(), 0
        for index, row in enumerate(trades):
            a.observe("trades", row)
            before = len(a.issues)
            for key in CORE:
                a.check(row.get(key) is not None and row.get(key) != "", "missing_trade_" + key, mid, "trades", index)
            p, size, ts, oi = (row.get(k) for k in ("price", "size", "timestamp", "outcomeIndex"))
            a.check(finite_number(p) and 0 <= p <= 1, "invalid_trade_price", mid, "trades", index)
            a.check(finite_number(size) and size > 0, "invalid_trade_size", mid, "trades", index)
            a.check(integer_time(ts) and lo <= ts <= hi, "invalid_trade_timestamp", mid, "trades", index)
            a.check(row.get("side") in ("BUY", "SELL"), "invalid_trade_side", mid, "trades", index)
            a.check(bool(HEX40.fullmatch(str(row.get("proxyWallet", "")))), "invalid_wallet", mid, "trades", index)
            a.check(bool(HEX64.fullmatch(str(row.get("transactionHash", "")))), "invalid_transaction_hash", mid, "trades", index)
            a.check(row.get("conditionId") == candidate["condition_id"], "trade_condition_join", mid, "trades", index)
            a.check(type(oi) is int and oi in (0, 1), "invalid_outcome_index", mid, "trades", index)
            if type(oi) is int and oi in (0, 1):
                a.check(row.get("asset") == tokens[oi], "trade_asset_index_join", mid, "trades", index)
                # IDs/index are the join. Text differences are a separate display-label diagnostic.
                a.check(row.get("outcome") == outcomes[oi], "trade_outcome_label_difference", mid, "trades", index,
                        detail=f"{row.get('outcome')} -> {outcomes[oi]}", severity="warning")
            if any(issue["severity"] == "error" for issue in a.issues[before:]):
                bad_trade_rows.add(index)
            if finite_number(p) and finite_number(size):
                notionals.append(p * size)
                sizes.append(size)
                tprices.append(p)
                edge_trades += p in (0, 1)
                if p * size > 500000:
                    large_rows.append(dict(market_id=mid, topic=topic, source_row_index=index,
                        price=p, size=size, row_notional=p*size, transaction_hash=row.get("transactionHash"),
                        source=(folder/"trades_window.json.gz").relative_to(BASE).as_posix()))
            if integer_time(ts):
                times.append(ts)
            wallet = str(row.get("proxyWallet", ""))
            wallet_raw.add(wallet)
            wallets.add(wallet.lower())
            wallet_spellings[wallet.lower()].add(wallet)
            wallet_profiles[wallet.lower()].add((row.get("name"), row.get("pseudonym"), row.get("bio"), row.get("profileImage")))
            exact[json.dumps(row, sort_keys=True, separators=(",", ":"))].append(index)
            key = economic_key(row)
            economic[key].append(index)
            tx = str(row.get("transactionHash", "")).lower()
            tx_rows[tx] += 1
            tx_keys[tx].add(key)
            tx_markets[tx].add(mid)
            trade_categories[f"{row.get('side')}|outcome_{oi}"] += 1
        unique_by_tx = defaultdict(list)
        for group in exact.values():
            row = trades[group[0]]
            unique_by_tx[row["transactionHash"]].append(row)
        for group in unique_by_tx.values():
            if len(group) != 2:
                continue
            x, y = group
            if x["asset"] == y["asset"] and x["side"] != y["side"]:
                tx_pair_patterns["same_token_opposite_sides"] += 1
            elif x["asset"] != y["asset"] and x["side"] == y["side"]:
                tx_pair_patterns["opposite_tokens_same_side"] += 1
            else:
                tx_pair_patterns["other_two_row_pattern"] += 1
        exact_excess = sum(len(group) - 1 for group in exact.values())
        economic_excess = sum(len(group) - 1 for group in economic.values())
        duplicate_notional = 0
        for kind, groups in (("exact_row", exact), ("economic_signature", economic)):
            for group in groups.values():
                if len(group) < 2:
                    continue
                first = trades[group[0]]
                differing = [k for k in set().union(*(trades[i] for i in group))
                             if len({json.dumps(trades[i].get(k), sort_keys=True) for i in group}) > 1]
                extra = sum(trades[i]["price"] * trades[i]["size"] for i in group[1:])
                if kind == "exact_row":
                    duplicate_notional += extra
                duplicates.append(dict(market_id=mid, topic=topic, kind=kind, rows=len(group), excess_rows=len(group)-1,
                    source_row_indices=json.dumps(group), transaction_hash=first["transactionHash"],
                    differing_fields=";".join(sorted(differing)), excess_notional=extra,
                    source=(folder / "trades_window.json.gz").relative_to(BASE).as_posix()))
        a.check(exact_excess == result["exact_duplicate_candidates"], "duplicate_count_reconciliation", mid)
        a.check(len(wallet_raw) == result["observed_wallets"], "wallet_count_reconciliation", mid)
        ptimes, pvalues, pt_groups = [], [], defaultdict(list)
        for index, row in enumerate(prices):
            a.observe("hourly_prices", row)
            ts, p = row.get("t"), row.get("p")
            a.check(integer_time(ts) and lo <= ts <= hi, "invalid_price_timestamp", mid, "prices", index)
            a.check(finite_number(p) and 0 <= p <= 1, "invalid_history_price", mid, "prices", index)
            if integer_time(ts) and finite_number(p):
                ptimes.append(ts)
                pvalues.append(p)
                pt_groups[ts].append(p)
        ordered = sorted(zip(ptimes, pvalues))
        gaps = [y[0] - x[0] for x, y in zip(ordered, ordered[1:])]
        jumps = [abs(y[1] - x[1]) for x, y in zip(ordered, ordered[1:])]
        valid_raw = [r for r in raw_prices if integer_time(r.get("t")) and finite_number(r.get("p")) and 0 <= r["p"] <= 1]
        raw_invalid = len(raw_prices) - len(valid_raw)
        raw_outside = sum(not lo <= r["t"] <= hi for r in valid_raw)
        a.check(prices == sorted([r for r in valid_raw if lo <= r["t"] <= hi], key=lambda r:r["t"]), "hourly_filter_reconciliation", mid)
        conflict = sum(len(set(v)) > 1 for v in pt_groups.values())
        a.check(conflict == 0, "conflicting_price_timestamp", mid, "prices", detail=str(conflict))
        is_fallback = result.get("cutoff_price_source") == "one_minute_fallback"
        snapshot = a.json(folder / "cutoff_price_fallback.json.gz")["history"] if is_fallback else prices
        fresh = sorted([r for r in snapshot if integer_time(r.get("t")) and finite_number(r.get("p"))
                        and 0 <= r["p"] <= 1 and max(lo, hi - 21600) <= r["t"] <= hi], key=lambda r:r["t"])
        a.check(bool(fresh), "missing_fresh_cutoff", mid)
        if fresh:
            a.check(fresh[-1]["p"] == result["forecast_probability"] == float(reg["forecast_probability"]), "snapshot_probability_join", mid)
            a.check(hi - fresh[-1]["t"] == result["forecast_price_age_seconds"] == float(reg["forecast_price_age_seconds"]), "snapshot_age_join", mid)
        d = dict(market_id=mid, topic=topic, question=candidate["question"], event_family_id=reg["event_family_id"],
            event_month=reg["reviewed_anchor_utc"][:7], window_hours=(hi-lo)/3600,
            original_anchor_differs=stamp(candidate["anchor"]) != stamp(reg["reviewed_anchor_utc"]),
            fractional_second_cutoff=stamp(reg["reviewed_cutoff_utc"]) != hi,
            subsecond_floor_difference=stamp(reg["reviewed_cutoff_utc"])-hi,
            sampling_month_differs=candidate["sampling_month"] != reg["reviewed_anchor_utc"][:7],
            missing_sampling_probability=not candidate["event_inclusion_probability"],
            missing_reported_volume=not candidate["reported_volume"],
            replacement=bool(candidate["replaces_market_id"]), trade_rows=len(trades), wallets=len(wallets),
            invalid_trade_rows=len(bad_trade_rows), exact_duplicate_excess=exact_excess,
            economic_duplicate_excess=economic_excess, trade_rows_ascending=times == sorted(times),
            raw_row_notional=sum(notionals), exact_duplicate_excess_notional=duplicate_notional,
            exact_dedup_scenario_notional=sum(notionals)-duplicate_notional,
            boundary_price_trade_rows=edge_trades, price_points=len(prices), price_rows_ascending=ptimes == sorted(ptimes),
            price_duplicate_excess=sum(len(v)-len(set(v)) for v in pt_groups.values()),
            price_conflicting_timestamps=conflict, raw_price_invalid_rows=raw_invalid, raw_price_outside_window=raw_outside,
            price_gap_max_seconds=max(gaps, default=None), price_gap_median_seconds=distribution(gaps).get("median"),
            price_gaps_over_90_minutes=sum(g>5400 for g in gaps), price_gaps_over_6_hours=sum(g>21600 for g in gaps),
            leading_price_gap_seconds=min(ptimes)-lo if ptimes else None,
            trailing_price_gap_seconds=hi-max(ptimes) if ptimes else None,
            flat_price_series=len(pvalues)>=2 and len(set(pvalues))==1,
            max_observed_price_step=max(jumps, default=None), price_steps_ge_20pp=sum(j>=.2 for j in jumps),
            cutoff_fallback=is_fallback, forecast_probability=result["forecast_probability"],
            forecast_price_age_seconds=result["forecast_price_age_seconds"],
            option_count_status=options["option_count_status"], capture_path=coverage["capture_path"])
        per_market.append(d)
        totals.update(trades=len(trades), hourly_prices=len(prices), raw_price_invalid=raw_invalid,
                      raw_price_outside_window=raw_outside, exact_duplicate_excess=exact_excess,
                      economic_duplicate_excess=economic_excess, boundary_price_trades=edge_trades,
                      boundary_hourly_prices=sum(p in (0,1) for p in pvalues),
                      exact_price_duplicate_excess=d["price_duplicate_excess"], price_conflicting_timestamps=conflict,
                      price_intervals=len(gaps), intervals_not_exactly_one_hour=sum(g!=3600 for g in gaps),
                      intervals_outside_one_hour_plus_minus_minute=sum(abs(g-3600)>60 for g in gaps))
        for key, values in (("trade_size",sizes), ("trade_price",tprices), ("row_notional",notionals),
                            ("price_interval_seconds",gaps), ("observed_price_step",jumps)):
            value_lists[key].extend(values)
        for key in ("trade_rows", "wallets", "window_hours", "price_points", "raw_row_notional",
                    "forecast_price_age_seconds", "forecast_probability", "price_gap_max_seconds"):
            value_lists[key].append(d[key])
            topic_values[topic][key].append(d[key])
        if ordinal % 100 == 0 or ordinal == len(candidates):
            print(f"Audited {ordinal}/{len(candidates)} markets", flush=True)
    for label, groups in (("condition", conditions), ("token", tokens_seen)):
        for key, mids in groups.items():
            a.check(len(mids) == 1, "nonunique_" + label, ";".join(sorted(mids)), detail=key)
    families = Counter(r["event_family_id"] for r in per_market)
    summary = dict(created_at_utc=datetime.now(timezone.utc).isoformat(), scope="general_eda_audit_only",
        markets=len(candidates), totals=dict(totals), market_categories=dict(market_categories),
        event_families=len(families), multi_market_families=sum(v>1 for v in families.values()),
        integrity_issue_counts=dict(a.counts), integrity_issue_records=len(a.issues),
        integrity_error_records=sum(r["severity"]=="error" for r in a.issues),
        integrity_warning_records=sum(r["severity"]=="warning" for r in a.issues),
        unique_wallets=len(wallet_spellings), wallets_with_case_variants=sum(len(s)>1 for s in wallet_spellings.values()),
        wallets_with_multiple_profile_snapshots=sum(len(s)>1 for s in wallet_profiles.values()),
        unique_transaction_hashes=len(tx_rows), hashes_with_multiple_rows=sum(n>1 for n in tx_rows.values()),
        hashes_with_distinct_economic_rows=sum(len(s)>1 for s in tx_keys.values()),
        hashes_spanning_markets=sum(len(s)>1 for s in tx_markets.values()),
        economic_rows_per_hash_distribution=distribution([len(s) for s in tx_keys.values()]),
        hashes_with_two_distinct_rows=sum(len(s)==2 for s in tx_keys.values()),
        two_row_transaction_patterns=dict(tx_pair_patterns), large_notional_row_threshold=500000,
        large_notional_rows=len(large_rows),
        trade_side_and_outcome=dict(trade_categories), distributions={k:distribution(v) for k,v in value_lists.items()},
        market_flags={k:sum(bool(r[k]) for r in per_market) for k in (
            "original_anchor_differs", "fractional_second_cutoff", "sampling_month_differs", "missing_sampling_probability", "missing_reported_volume", "replacement",
            "exact_duplicate_excess", "economic_duplicate_excess", "invalid_trade_rows", "cutoff_fallback",
            "raw_price_invalid_rows", "price_duplicate_excess", "price_conflicting_timestamps", "flat_price_series",
            "price_gaps_over_90_minutes", "price_gaps_over_6_hours", "price_steps_ge_20pp")},
        zero_trade_markets=sum(r["trade_rows"]==0 for r in per_market),
        short_window_markets=sum(r["window_hours"]<168 for r in per_market),
        empty_hourly_histories=sum(r["price_points"]==0 for r in per_market),
        fewer_than_two_hourly_points=sum(r["price_points"]<2 for r in per_market),
        trade_windows_not_ascending=sum(not r["trade_rows_ascending"] for r in per_market),
        price_windows_not_ascending=sum(not r["price_rows_ascending"] for r in per_market),
        hourly_trailing_gap_over_six_hours=sum((r["trailing_price_gap_seconds"] or 0)>21600 for r in per_market),
        raw_row_notional=sum(r["raw_row_notional"] for r in per_market),
        exact_duplicate_excess_notional=sum(r["exact_duplicate_excess_notional"] for r in per_market),
        exact_duplicate_groups=sum(r["kind"]=="exact_row" for r in duplicates),
        top_ten_markets_by_raw_row_notional=[{k:r[k] for k in ("market_id","topic","question","raw_row_notional")}
            for r in sorted(per_market,key=lambda r:r["raw_row_notional"],reverse=True)[:10]],
        economic_groups_with_nonidentical_fields=sum(bool(r["differing_fields"]) for r in duplicates if r["kind"]=="economic_signature"),
        topic_summary={topic:dict(markets=len(values["trade_rows"]), trade_rows=sum(values["trade_rows"]),
            hourly_prices=sum(values["price_points"]), zero_trade_markets=values["trade_rows"].count(0),
            short_windows=sum(h<168 for h in values["window_hours"]),
            distributions={k:distribution(v) for k,v in values.items()}) for topic,values in topic_values.items()},
        limitations=["Returned rows are not certified unique fills; economic signature is diagnostic only.",
            "Price*size sums describe returned account rows from takerOnly=false, not reconciled exchange volume.",
            "No live API calls, external fact re-audit, cleaning, model normalization, or cohort changes.",
            "Prices are first-token observations; cutoff fallback observations remain separate.",
            "Intervals/jumps describe observed points without regular-grid resampling or interpolation."])
    fields=[]
    for table,p in a.profile.items():
        for field,f in p["fields"].items():
            fields.append(dict(table=table, field=field, rows=p["rows"], absent=p["rows"]-f["present"],
                null_or_empty=f["blank"], total_missing=p["rows"]-f["present"]+f["blank"], types=json.dumps(f["types"],sort_keys=True)))
    # Prevent accidental replacement of a dated audit if its source inputs changed.
    manifest_path = OUT / "input_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_data = {k:v for k,v in previous["sha256"].items() if not k.startswith("src/")}
        current_data = {k:v for k,v in a.inputs.items() if not k.startswith("src/")}
        if any(current_data.get(k) != v for k,v in previous_data.items()):
            raise RuntimeError("Source data changed. Use a new dated output directory.")
    changed = [p for p,digest in a.inputs.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest]
    if changed:
        raise RuntimeError(f"Inputs changed during audit: {changed}")
    OUT.mkdir(exist_ok=True)
    summary["input_files_hashed_and_unchanged"] = len(a.inputs)
    (OUT / "summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    manifest_path.write_text(json.dumps(dict(sha256=a.inputs),indent=2)+"\n",encoding="utf-8")
    write_csv(OUT / "market_diagnostics.csv", per_market)
    write_csv(OUT / "field_profile.csv", fields)
    write_csv(OUT / "duplicate_groups.csv", duplicates,
              ["market_id","topic","kind","rows","excess_rows","source_row_indices","transaction_hash","differing_fields","excess_notional","source"])
    write_csv(OUT / "integrity_issues.csv", a.issues,["market_id","table","source_row_index","issue","severity","detail"])
    write_csv(OUT / "large_rows.csv", large_rows,["market_id","topic","source_row_index","price","size","row_notional","transaction_hash","source"])
    print(json.dumps({k:summary[k] for k in ("markets","totals","integrity_issue_counts","market_flags",
        "empty_hourly_histories","fewer_than_two_hourly_points","unique_wallets","unique_transaction_hashes",
        "hashes_with_distinct_economic_rows","hashes_spanning_markets","economic_groups_with_nonidentical_fields",
        "input_files_hashed_and_unchanged")},indent=2))


if __name__ == "__main__":
    main()
