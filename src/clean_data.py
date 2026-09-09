"""Build auditable prototype CSVs offline from one captured API run."""
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from prove_data import ROOT, json_list

DOMAINS = {"politics": "Politics", "sports": "Sports", "crypto": "Crypto",
           "economy": "Economy", "finance": "Finance", "business": "Business",
           "tech": "Technology", "pop-culture": "Culture", "science": "Science",
           "climate": "Climate", "geopolitics": "Geopolitics"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def epoch(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()) if value else None


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def category(market):
    tags = market.get("tags", [])
    labels = sorted({DOMAINS[t["slug"]] for t in tags if t.get("slug") in DOMAINS})
    return ";".join(labels) or "Unclassified"


def resolved_outcome(market):
    """Conservative label from Gamma's explicit status AND a unique one-hot payout."""
    outcomes = json_list(market.get("outcomes"))
    prices = [number(p) for p in json_list(market.get("outcomePrices"))]
    if (market.get("closed") is True and market.get("umaResolutionStatus") == "resolved"
            and len(prices) == len(outcomes) >= 2 and prices.count(1.0) == 1
            and all(p in (0.0, 1.0) for p in prices)):
        winner = prices.index(1.0)
        return outcomes[winner], int(winner == 0), "gamma_resolved_and_one_hot_prices"
    return None, None, "unverified"


def snapshot(market, days, payload):
    """Only use a prior observation within six hours; never backfill from the future."""
    anchor, opened = epoch(market.get("closedTime")), epoch(market.get("startDate"))
    result = {"price": None, "timestamp": None, "age_seconds": None, "status": "missing_anchor"}
    if anchor is None:
        return result
    target = anchor - days * 86400
    if opened is not None and target < opened:
        result["status"] = "market_not_open"
        return result
    if payload is None or "history" not in payload:
        result["status"] = "not_retrieved_or_request_failed"
        return result
    valid = [p for p in payload["history"] if number(p.get("t")) is not None
             and target - 6 * 3600 <= float(p["t"]) <= target
             and number(p.get("p")) is not None and 0 <= float(p["p"]) <= 1
             and (opened is None or float(p["t"]) >= opened)]
    if not valid:
        result["status"] = "no_observation_in_window"
        return result
    point = max(valid, key=lambda p: float(p["t"]))
    return {"price": float(point["p"]), "timestamp": utc(int(point["t"])),
            "age_seconds": target - int(point["t"]), "status": "available"}


def normalize_trade(row, markets, cutoff):
    market = markets.get(row.get("conditionId"))
    if not market:
        raise ValueError("market_not_joined")
    wallet = row.get("proxyWallet", "")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet):
        raise ValueError("invalid_wallet")
    price, size, stamp = (number(row.get(k)) for k in ("price", "size", "timestamp"))
    if price is None or not 0 <= price <= 1 or size is None or size <= 0:
        raise ValueError("invalid_price_or_size")
    if stamp is None or stamp <= 0 or stamp > cutoff or not stamp.is_integer():
        raise ValueError("invalid_timestamp")
    if row.get("side") not in ("BUY", "SELL"):
        raise ValueError("invalid_side")
    tokens, outcomes = json_list(market.get("clobTokenIds")), json_list(market.get("outcomes"))
    asset = str(row.get("asset", ""))
    if asset not in tokens:
        raise ValueError("asset_not_joined")
    index = tokens.index(asset)
    if index >= len(outcomes) or row.get("outcomeIndex") != index or row.get("outcome") != outcomes[index]:
        raise ValueError("outcome_mismatch")
    return {"market_id": market["id"], "condition_id": market["conditionId"],
            "wallet": wallet.lower(), "category": category(market),
            "timestamp": int(stamp), "timestamp_utc": utc(stamp), "side": row["side"],
            "outcome": outcomes[index], "outcome_index": index, "asset_id": asset,
            "price": price, "size_shares": size, "notional_usdc": price * size,
            "transaction_hash": row.get("transactionHash")}


def write_csv(path, rows, fields=None):
    if not rows and not fields:
        raise ValueError(f"No rows or schema for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="Captured run directory; defaults to latest completed run")
    args = parser.parse_args()
    completed = sorted(p.parent for p in (ROOT / "data/raw").glob("*/selection.json"))
    if not args.run and not completed:
        raise SystemExit("No completed capture found. Run python src/prove_data.py first.")
    raw = args.run.resolve() if args.run else completed[-1]
    selection, manifest = read(raw / "selection.json"), read(raw / "manifest.json")
    for record in manifest:
        body = (raw / record["file"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != record["sha256"]:
            raise ValueError(f"Raw response changed: {record['file']}")
    selected = read(raw / "selected_markets.json")
    markets = {m["conditionId"]: m for m in selected}
    for path in sorted(raw.glob("wallet_markets_*.json")):
        payload = read(path)
        if isinstance(payload, list):
            markets.update({m["conditionId"]: m for m in payload})
    rejected, duplicates = [], {}

    def normalized(pattern, activity=False):
        output, seen, duplicate_count = [], set(), 0
        for path in sorted(raw.glob(pattern)):
            payload = read(path)
            if not isinstance(payload, list):
                continue
            for i, row in enumerate(payload):
                if activity and row.get("type") != "TRADE":
                    continue
                fingerprint = json.dumps(row, sort_keys=True)
                duplicate_count += fingerprint in seen
                seen.add(fingerprint)
                try:
                    item = normalize_trade(row, markets, selection["cutoff_timestamp"])
                    if not activity and item["market_id"] != path.stem.split("_")[1]:
                        raise ValueError("market_filter_mismatch")
                    if activity and item["wallet"] != selection["wallet"].lower():
                        raise ValueError("wallet_filter_mismatch")
                    item.update(source_file=path.name, source_row=i)
                    output.append(item)
                except ValueError as error:
                    rejected.append({"source_file": path.name, "source_row": i, "reason": str(error)})
        # Keep duplicate candidates: these endpoints provide no unique fill/log ID.
        duplicates[pattern] = duplicate_count
        return output

    trades = normalized("trades_*_*.json")
    activity_trades = normalized("wallet_activity_*.json", activity=True)
    by_market, by_category = defaultdict(list), defaultdict(list)
    for row in trades:
        by_market[row["condition_id"]].append(row)
    for row in activity_trades:
        by_category[(row["wallet"], row["category"])].append(row)
    market_rows = []
    for market in selected:
        cid = market["conditionId"]
        rows = by_market[cid]
        outcomes = json_list(market.get("outcomes"))
        resolution, final_outcome, source = resolved_outcome(market)
        notionals = defaultdict(float)
        for row in rows:
            notionals[row["wallet"]] += row["notional_usdc"]
        total = sum(notionals.values())
        item = {"market_id": market["id"], "condition_id": cid, "question": market["question"],
            "category": category(market), "category_source": "exact_tag_slug_mapping_v1",
            "raw_category": market.get("category"),
            "tag_slugs": ";".join(sorted(t["slug"] for t in market.get("tags", []) if t.get("slug"))),
            "resolution": resolution, "resolution_source": source, "final_outcome": final_outcome,
            "forecast_outcome": outcomes[0] if outcomes else None,
            "start_date_utc": market.get("startDate"), "scheduled_end_date_utc": market.get("endDate"),
            "closed_time_utc": utc(epoch(market.get("closedTime"))),
            "total_volume_reported": number(market.get("volumeNum", market.get("volume"))),
            "sample_trade_rows": len(rows), "sample_number_traders": len(notionals),
            "sample_volume_usdc": total if rows else None,
            "sample_trader_concentration_hhi": sum((v / total) ** 2 for v in notionals.values()) if total > 0 else None,
            "sample_avg_trade_size_shares": sum(r["size_shares"] for r in rows) / len(rows) if rows else None,
            "sample_largest_trade_shares": max((r["size_shares"] for r in rows), default=None),
            "sample_first_trade_utc": utc(min((r["timestamp"] for r in rows), default=None)),
            "sample_last_trade_utc": utc(max((r["timestamp"] for r in rows), default=None)),
            "trade_stop_reason": selection["market_trade_coverage"][cid]["stop_reason"],
            "full_trade_history_verified": False}
        for days in (30, 7, 1):
            path = raw / f"prices_{market['id']}_{days}d.json"
            value = snapshot(market, days, read(path) if path.exists() else None)
            item[f"price_{days}_days_before"] = value["price"]
            item[f"price_{days}d_observed_at_utc"] = value["timestamp"]
            item[f"price_{days}d_age_seconds"] = value["age_seconds"]
            item[f"price_{days}d_status"] = value["status"]
        market_rows.append(item)
    wallet_rows = []
    for (wallet, domain), rows in sorted(by_category.items()):
        buys = [r for r in rows if r["side"] == "BUY"]
        shares = sum(r["size_shares"] for r in buys)
        wallet_rows.append({"wallet": wallet, "category": domain,
            "sample_num_trades": len(rows), "sample_num_buy_trades": len(buys),
            "sample_num_markets": len({r["condition_id"] for r in rows}),
            "sample_volume_usdc": sum(r["notional_usdc"] for r in rows),
            "sample_avg_entry_probability": sum(r["notional_usdc"] for r in buys) / shares if shares else None,
            "profit": None, "win_rate": None, "roi": None,
            "performance_status": "not_estimable_from_partial_activity_and_inventory",
            "sample_first_trade_utc": utc(min(r["timestamp"] for r in rows)),
            "sample_last_trade_utc": utc(max(r["timestamp"] for r in rows)),
            "full_wallet_history_verified": False})
    clean = ROOT / "data/clean" / raw.name
    clean.mkdir(parents=True, exist_ok=True)
    trade_fields = ["market_id", "condition_id", "wallet", "category", "timestamp", "timestamp_utc",
                    "side", "outcome", "outcome_index", "asset_id", "price", "size_shares", "notional_usdc",
                    "transaction_hash", "source_file", "source_row"]
    write_csv(clean / "markets.csv", market_rows)
    write_csv(clean / "trades.csv", trades, trade_fields)
    write_csv(clean / "wallet_trades.csv", activity_trades, trade_fields)
    wallet_fields = ["wallet", "category", "sample_num_trades", "sample_num_buy_trades", "sample_num_markets",
                     "sample_volume_usdc", "sample_avg_entry_probability", "profit", "win_rate", "roi",
                     "performance_status", "sample_first_trade_utc", "sample_last_trade_utc", "full_wallet_history_verified"]
    write_csv(clean / "wallet_category.csv", wallet_rows, wallet_fields)
    all_activity = [r for p in sorted(raw.glob("wallet_activity_*.json"))
                    for r in (read(p) if isinstance(read(p), list) else [])]
    report = {"wallet_activity_types": dict(Counter(r.get("type") for r in all_activity)),
        "wallet_activity_records": len(all_activity), "run_id": raw.name, "markets": len(market_rows), "joined_market_trade_rows": len(trades),
        "distinct_sample_wallets": len({r["wallet"] for r in trades}),
        "wallet_activity_trade_rows_joined": len(activity_trades), "wallet_category_rows": len(wallet_rows),
        "resolved_labels": sum(r["resolution"] is not None for r in market_rows),
        "raw_category_missing": sum(not m.get("category") for m in selected),
        "multiple_domain_markets": sum(";" in r["category"] for r in market_rows),
        "trade_stop_reasons": dict(Counter(r["trade_stop_reason"] for r in market_rows)),
        "price_coverage": {str(d): dict(Counter(r[f"price_{d}d_status"] for r in market_rows)) for d in (30, 7, 1)},
        "duplicate_candidates_retained": duplicates, "rejected_rows": rejected,
        "api_errors": [r for r in manifest if "error" in r],
        "wallet_category_counts": {r["category"]: r["sample_num_trades"] for r in wallet_rows},
        "example_market": next((r for r in market_rows if by_market[r["condition_id"]]), None),
        "example_trade": trades[0] if trades else None}
    (clean / "quality_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if not k.startswith("example_") and k != "rejected_rows"}, indent=2))
    print(f"Rejected rows: {len(rejected)}; details in quality_report.json")
    print(f"Prototype tables saved to {clean}")


if __name__ == "__main__":
    main()
