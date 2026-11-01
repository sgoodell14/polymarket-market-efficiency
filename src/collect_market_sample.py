
import argparse
import csv
import gzip
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

# bring in sample-data folder location and a CSV-writing helper
from prepare_sampling_plan import OUTPUT, write_csv


# gamma base address
GAMMA = "https://gamma-api.polymarket.com"

# map topic names to tags 
TAGS = {"sports": 1, "politics": 2, "economy": 100328, "economics": 225}

# up to 8 at once 
NETWORK_SLOTS = threading.BoundedSemaphore(8)

# 1000 records at a time 
PAGE_SIZE = 1000

# default cap of 50 trade requests per market 
MAX_TRADE_REQUESTS = 50


# API requests / market metadata

# convert date as text to python date-time 
def stamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return None

# api function 
def fetch(folder, name, base, path, **params):
    folder.mkdir(parents=True, exist_ok=True)
    # construct url 
    url = base + path + "?" + urllib.parse.urlencode(params, doseq=True)
    datafile, metafile = folder / (name + ".json.gz"), folder / (name + ".request.json")
    # check if it has a saved resposne 
    if datafile.exists() and metafile.exists():
        meta = json.loads(metafile.read_text(encoding="utf-8"))
        body = gzip.decompress(datafile.read_bytes())
        if meta["url"] != url or hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise ValueError(f"Cache mismatch: {datafile}")
        return json.loads(body)
    # create request if not saved 
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; MarketEfficiencyResearch/0.1)",
        "Accept": "application/json"})
    # retry up to 4 times for temp failures 
    for attempt in range(4):
        try:
            with NETWORK_SLOTS:
                with urllib.request.urlopen(request, timeout=40) as response:
                    body, status = response.read(), response.status
            payload = json.loads(body)
            datafile.write_bytes(gzip.compress(body))
            metafile.write_text(json.dumps({"url": url, "status": status,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(body).hexdigest()}, indent=2), encoding="utf-8")
            return payload
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 3 or (isinstance(error, urllib.error.HTTPError)
                               and error.code not in (429, 500, 502, 503, 504)):
                raise
            time.sleep(2 ** attempt)

# convert JSON text to list 
def json_list(value):
    return json.loads(value) if isinstance(value, str) else (value or [])

# convert numeric text to float
def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


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


def screen_market(m, topic):
    tags = {t["slug"].lower() for t in m.get("tags", [])}
    mention = "mention-markets" in tags
    if topic == "Sports":
        subtype = "game_winner"
    elif mention:
        subtype = "mentions"
    elif topic == "Politics":
        subtype = "elections" if tags & {"elections", "global-elections", "world-elections", "primaries", "primary-elections"} else "other"
    else:
        subtype = "macro_policy" if tags & {"macro-indicators", "inflation", "cpi", "gdp", "unemployment", "jobs-report", "fed-rates", "global-rates", "fomc", "cpi-release"} else "other"
    outcomes, tokens = json_list(m.get("outcomes")), json_list(m.get("clobTokenIds"))
    resolution, final, _ = resolved_outcome(m)
    basic = bool(resolution is not None and len(outcomes) == len(tokens) == 2 and m.get("conditionId"))
    events = m.get("events", [])
    explicit = []
    if stamp(m.get("gameStartTime")):
        explicit.append((stamp(m["gameStartTime"]), "gameStartTime"))
    for event in events:
        if stamp(event.get("startTime")):
            explicit.append((stamp(event["startTime"]), "event.startTime"))
    conflict = bool(explicit and max(t[0] for t in explicit) - min(t[0] for t in explicit) > timedelta(hours=1))
    anchor, source = explicit[0] if explicit else (stamp(m.get("endDate")), "endDate_proxy")
    start, closed = stamp(m.get("startDate")), stamp(m.get("closedTime"))
    row = {"topic": topic, "subtype": subtype, "is_mention": mention, "market_id": str(m["id"]),
           "question": m["question"], "slug": m.get("slug"),
           "condition_id": m.get("conditionId"), "first_token_id": str(tokens[0]) if tokens else "",
           "event_ids": ";".join(str(e["id"]) for e in events),
           "tag_slugs": ";".join(sorted(tags)), "start_date": m.get("startDate"),
           "end_date": m.get("endDate"), "closed_time": m.get("closedTime"),
           "anchor": anchor.isoformat() if anchor else "", "anchor_source": source,
           "anchor_conflict": conflict, "binary_resolved": basic, "final_outcome": final,
           "reported_volume": m.get("volumeNum", m.get("volume")),
           "closed_before_anchor": bool(closed and anchor and closed < anchor)}
    for hours in (1, 24, 168):
        row[f"candidate_{hours}h"] = bool(basic and anchor and start and closed and
            start <= anchor - timedelta(hours=hours) and closed >= anchor - timedelta(hours=hours) and not conflict)
    return row


# Candidate inventory by topic and month.


def months(start, end):
    current = stamp(start)
    stop = stamp(end)
    while current < stop:
        following = current.replace(year=current.year + (current.month == 12),
                                    month=current.month % 12 + 1, day=1)
        yield current, min(following, stop)
        current = following


def inventory_month(run, slug, lower, upper, depth=0, sports_cursor=False):
    period = lower.strftime("%Y-%m") if depth == 0 else lower.strftime("%Y%m%dT%H%M%S") + "_" + upper.strftime("%Y%m%dT%H%M%S")
    group = ("sports_moneyline_keyset" if sports_cursor else "sports_moneyline") if slug == "sports" else slug
    folder = run / "inventory" / group / period
    folder.mkdir(parents=True, exist_ok=True)
    cursor, seen_cursors, markets, pages = None, set(), {}, 0
    while True:
        # The legacy endpoint caps offsets at 2000. Partition the time interval
        # instead of treating that cap as the end of the available records.
        if slug == "sports" and not sports_cursor and pages == 21:
            if depth >= 15:
                raise ValueError("Sports interval remains too dense after partitioning")
            middle = lower + (upper - lower) / 2
            combined = {}
            intervals = [(lower, middle), (middle, upper)]
            if depth < 3:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    parts = list(pool.map(lambda bounds: inventory_month(run, slug, *bounds, depth + 1), intervals))
            else:
                parts = [inventory_month(run, slug, first, last, depth + 1) for first, last in intervals]
            for _, subset, _ in parts:
                combined.update(subset)
            summary = {"slug": slug, "month": lower.strftime("%Y-%m"),
                       "count": len(combined), "pagination_complete": True, "partitioned": True}
            (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            if depth == 0:
                print("DONE", json.dumps(summary), flush=True)
            return slug, combined, summary
        params = dict(tag_id=TAGS[slug], closed="true", include_tag="true", limit=100,
                      order="id", ascending="true", end_date_min=lower.isoformat(),
                      end_date_max=upper.isoformat())
        if slug == "sports":
            params["sports_market_types"] = ["moneyline"]
            if not sports_cursor:
                params["offset"] = pages * 100
        if cursor and (slug != "sports" or sports_cursor):
            params["after_cursor"] = cursor
        payload = fetch(folder, f"page_{pages:05}", GAMMA,
                        "/markets" if slug == "sports" and not sports_cursor else "/markets/keyset", **params)
        if slug == "sports" and not sports_cursor and isinstance(payload, list):
            payload = {"markets": payload, "next_cursor": str(pages + 1) if len(payload) == 100 else None}
        if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
            raise ValueError(f"Unexpected response for {slug} {lower}")
        for market in payload["markets"]:
            if slug == "sports" and market.get("sportsMarketType") != "moneyline":
                raise ValueError("Server did not honor the moneyline filter")
            end = stamp(market.get("endDate"))
            if end and lower <= end < upper:
                markets[str(market["id"])] = market
        pages += 1
        if pages % 25 == 0:
            print(f"PROGRESS {slug} {lower:%Y-%m}: {pages} pages, {len(markets)} markets", flush=True)
        cursor = payload.get("next_cursor")
        if not cursor:
            break
        if cursor in seen_cursors:
            raise ValueError(f"Repeated cursor for {slug} {lower}")
        seen_cursors.add(cursor)
    summary = {"slug": slug, "month": lower.strftime("%Y-%m"), "pages": pages,
               "count": len(markets), "pagination_complete": True}
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if depth == 0:
        print("DONE", json.dumps(summary), flush=True)
    return slug, markets, summary


def collect_inventory(args):
    args.run.mkdir(parents=True, exist_ok=True)
    settings = {"start_inclusive": args.start, "end_exclusive": args.end,
                "time_field": "endDate (scheduled market end, not resolution date)",
                "tag_ids": {slug: TAGS[slug] for slug in args.tags}, "closed": True, "minimum_volume": None,
                "economics_topic": "Union of economy and economics exact tags",
                "sports_scope": "Individual game outcomes: sports_market_types=moneyline",
                "created_at_utc": datetime.now(timezone.utc).isoformat()}
    (args.run / "selection.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    by_tag, summaries, errors = {slug: {} for slug in args.tags}, [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(inventory_month, args.run, slug, lower, upper,
                             sports_cursor=slug == "sports" and not (args.run / "inventory" / "sports_moneyline" / lower.strftime("%Y-%m") / "summary.json").exists()): (slug, lower)
                 for lower, upper in months(args.start, args.end) for slug in args.tags}
        for task in as_completed(tasks):
            try:
                slug, markets, summary = task.result()
                by_tag[slug].update(markets)
                summaries.append(summary)
            except Exception as error:
                slug, lower = tasks[task]
                errors.append({"slug": slug, "month": str(lower), "error": str(error)})
                print("ERROR", errors[-1], flush=True)
    for slug, markets in by_tag.items():
        (args.run / (slug + "_markets.json.gz")).write_bytes(
            gzip.compress(json.dumps(list(markets.values())).encode()))
    result = {"counts": {k: len(v) for k, v in by_tag.items()},
              "months": summaries, "errors": errors,
              "pagination_complete": not errors}
    (args.run / "inventory_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("FINAL", json.dumps(result["counts"]), "errors", len(errors), flush=True)
    if errors:
        raise SystemExit(1)


# Metadata, trade windows, and price history for the selected sample.


def collect_trades(folder, condition, lower, upper, request=fetch, budget=MAX_TRADE_REQUESTS):
    """Bisect saturated inclusive-second windows; never infer completeness at cap.

    Request a one-second lower overlap, then filter locally. This tolerates
    either inclusive or exclusive API lower-bound semantics without losing
    same-second fills. Parent responses are replaced by disjoint child leaves.
    """
    calls = 0
    failures = []

    def window(lo, hi):
        nonlocal calls
        if calls >= budget:
            failures.append("request_budget_reached")
            return [], False
        calls += 1
        try:
            rows = request(folder, f"trades_{lo}_{hi}", "https://data-api.polymarket.com", "/trades",
                           market=condition, takerOnly="false", start=lo - 1, end=hi,
                           limit=PAGE_SIZE, offset=0)
            if not isinstance(rows, list):
                raise ValueError("Unexpected trade response")
            if any(t.get("conditionId") != condition or not isinstance(t.get("timestamp"), int)
                   or not lo - 1 <= t["timestamp"] <= hi for t in rows):
                raise ValueError("Trade market/time filter not honored")
            accepted = [t for t in rows if lo <= t["timestamp"] <= hi]
            if len(rows) < PAGE_SIZE:
                return accepted, True
            if lo == hi:
                failures.append("single_second_saturated")
                return accepted, False
            if calls >= budget:
                failures.append("request_budget_reached")
                return accepted, False
            mid = (lo + hi) // 2
            left, left_ok = window(lo, mid)
            right, right_ok = window(mid + 1, hi)
            if left_ok and right_ok:
                return left + right, True
            # Retain the parent sample when a child was incomplete. Do not
            # combine it with overlapping children or silently deduplicate fills.
            return accepted, False
        except Exception as error:
            failures.append(type(error).__name__ + ": " + str(error))
            return [], False

    rows, exhausted = window(lower, upper)
    return rows, exhausted, calls, sorted(set(failures))


def price_summary(history, lower, cutoff):
    valid = sorted([p for p in history if isinstance(p.get("t"), (int, float))
                    and lower <= p["t"] <= cutoff and isinstance(p.get("p"), (int, float))
                    and 0 <= p["p"] <= 1], key=lambda p: p["t"])
    recent = [p for p in valid if cutoff - p["t"] <= 21600]
    return valid, {"price_status": "available" if recent else "no_price_within_6h",
                   "price_points": len(valid), "forecast_probability": recent[-1]["p"] if recent else "",
                   "forecast_price_age_seconds": cutoff - recent[-1]["t"] if recent else "",
                   "max_price_gap_seconds": max([b["t"] - a["t"] for a, b in zip(valid, valid[1:])], default=0),
                   "price_first_timestamp": valid[0]["t"] if valid else "",
                   "price_last_timestamp": valid[-1]["t"] if valid else ""}


def cutoff_fallback_summary(hourly_stats, history, lower, cutoff):
    """Recover only the cutoff snapshot; leave hourly feature-series stats intact."""
    valid, fallback = price_summary(history, lower, cutoff)
    result = dict(hourly_stats, hourly_price_status=hourly_stats["price_status"],
                  cutoff_fallback_points=len(valid))
    if hourly_stats["price_status"] != "available" and fallback["price_status"] == "available":
        for key in ("price_status", "forecast_probability", "forecast_price_age_seconds"):
            result[key] = fallback[key]
        result.update(cutoff_price_source="one_minute_fallback",
                      cutoff_price_timestamp=cutoff - fallback["forecast_price_age_seconds"])
    return result


def collect_one(row, output_root=None, trade_budget=MAX_TRADE_REQUESTS):
    folder = (output_root or OUTPUT) / "pilot_collection" / row["market_id"]
    folder.mkdir(parents=True, exist_ok=True)
    result_path = folder / "result.json"
    started = time.perf_counter()
    cutoff = int(stamp(row["anchor"]).timestamp()) - 86400
    lower = max(cutoff - 7 * 86400, math.ceil(stamp(row["start_date"]).timestamp()))
    if lower > cutoff:
        raise ValueError("Market was not listed at the requested cutoff")
    if result_path.exists():
        cached = json.loads(result_path.read_text(encoding="utf-8"))
        if (cached["market_id"] != row["market_id"] or cached["anchor"] != row["anchor"]
                or cached["cutoff_timestamp"] != cutoff or cached["window_start_timestamp"] != lower):
            raise ValueError("Collection inputs changed; use a new collection run/version")
        return cached
    result = dict(topic=row["topic"], market_id=row["market_id"], question=row["question"],
                  event_ids=row["event_ids"], anchor=row["anchor"], anchor_source=row["anchor_source"],
                  event_time_verified=False, cutoff_timestamp=cutoff, window_start_timestamp=lower,
                  window_hours=max(0, cutoff - lower) / 3600,
                  shorter_than_seven_days=lower > cutoff - 7 * 86400,
                  full_trade_history_verified=False, modeling_ready=False)
    try:
        market = fetch(folder, "market", "https://gamma-api.polymarket.com", "/markets/" + row["market_id"])
        if str(market.get("id")) != row["market_id"] or market.get("conditionId") != row["condition_id"]:
            raise ValueError("Metadata identifier mismatch")
        result["metadata_status"] = "retrieved"
        result["rules_text_present"] = bool(market.get("description"))
        fresh = screen_market(market, row["topic"])
        # The detail endpoint can omit event.startTime; that is not evidence
        # that a scheduled event changed. Keep the inventory anchor for this run.
        result["detail_anchor_source"] = fresh["anchor_source"]
        result["detail_anchor_differs"] = fresh["anchor"] != row["anchor"]
    except Exception as error:
        result["metadata_status"] = "error: " + str(error)
    try:
        payload = fetch(folder, "prices_hourly", "https://clob.polymarket.com", "/prices-history",
                        market=row["first_token_id"], startTs=lower - 1, endTs=cutoff, fidelity=60)
        valid, stats = price_summary(payload["history"], lower, cutoff)
        result.update(stats)
        (folder / "prices_window.json.gz").write_bytes(gzip.compress(json.dumps(valid).encode()))
        if stats["price_status"] != "available":
            try:
                fallback_lower = max(lower, cutoff - 21600)
                fallback = fetch(folder, "cutoff_price_fallback", "https://clob.polymarket.com", "/prices-history",
                                 market=row["first_token_id"], startTs=fallback_lower - 1, endTs=cutoff, fidelity=1)
                result.update(cutoff_fallback_summary(stats, fallback["history"], fallback_lower, cutoff))
            except Exception as error:
                result["cutoff_fallback_error"] = str(error)
    except Exception as error:
        result.update(price_status="error: " + str(error), price_points=0)
    trades, exhausted, calls, errors = collect_trades(folder, row["condition_id"], lower, cutoff, budget=trade_budget)
    (folder / "trades_window.json.gz").write_bytes(gzip.compress(json.dumps(trades).encode()))
    # Exact duplicates remain in the captured data: transactionHash is not a
    # unique fill ID. Do not turn these diagnostics into volume/concentration yet.
    signatures = [json.dumps(t, sort_keys=True, separators=(",", ":")) for t in trades]
    result.update(trade_status="api_window_exhausted" if exhausted else "incomplete", trade_request_budget=trade_budget,
                  trade_requests=calls, trade_rows=len(trades), trade_errors="; ".join(errors),
                  observed_wallets=len({t["proxyWallet"] for t in trades if t.get("proxyWallet")}),
                  exact_duplicate_candidates=len(signatures) - len(set(signatures)),
                  earliest_trade_timestamp=min([t["timestamp"] for t in trades], default=""),
                  latest_trade_timestamp=max([t["timestamp"] for t in trades], default=""),
                  elapsed_seconds=round(time.perf_counter() - started, 3),
                  captured_at_utc=datetime.now(timezone.utc).isoformat())
    result["saved_payload_bytes"] = sum(p.stat().st_size for p in folder.glob("*.gz"))
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(row["topic"], row["market_id"], result["price_status"], result["trade_status"], len(trades), flush=True)
    return result


def collect_effective(row):
    """Use the latest approved capture without relabeling original histories."""
    index_path = OUTPUT / "corrections/active_corrections.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    if row["market_id"] not in index:
        return collect_one(row)
    root = OUTPUT / "corrections" / index[row["market_id"]]
    manifest = json.loads((root / "correction.json").read_text(encoding="utf-8"))
    revised = dict(row, anchor=stamp(manifest["corrected_anchor_utc"]).isoformat())
    return collect_one(revised, output_root=root)


def collect_sample(args):
    source = "active_candidates.csv" if args.scope == "full" else "active_pilot_candidates.csv"
    prefix = "active_cohort" if args.scope == "full" else "active_pilot"
    with (OUTPUT / source).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    from validate_market_sample import validate_membership
    if args.scope == 'full':
        validate_membership(rows)
    else:
        with (OUTPUT / 'active_candidates.csv').open(encoding='utf-8', newline='') as handle:
            full = list(csv.DictReader(handle))
        validate_membership(full)
        if len(rows) != len({r['market_id'] for r in rows}) or not {r['market_id'] for r in rows} <= {r['market_id'] for r in full}:
            raise ValueError('Pilot IDs must be unique and nested in the active cohort')
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(collect_effective, rows))
    write_csv(OUTPUT / (prefix + "_coverage.csv"), results)
    summary = {"scope": args.scope, "markets": len(results),
               "invocation_wall_seconds": round(time.perf_counter() - started, 3),
               "sum_market_collection_seconds": round(sum(r["elapsed_seconds"] for r in results), 3),
               "compressed_payload_bytes": sum(r["saved_payload_bytes"] for r in results),
               "trade_requests": sum(r["trade_requests"] for r in results),
               "trade_rows": sum(r["trade_rows"] for r in results),
               "price_points": sum(r["price_points"] for r in results),
               "topics": {},
               "limitations": ["Forecast cutoffs use provisional metadata, not verified actual event times.",
                               "API window exhaustion means all queried leaves returned below limit; not independent ledger reconciliation.",
                               "Initial collection uses 50 trade requests/market; targeted recoveries record their increased budget separately. Incomplete windows remain flagged.",
                               "Wallet identities/duplicate fills need review before activity features; no full wallet histories or orders collected."]}
    for topic in sorted({r["topic"] for r in results}):
        subset = [r for r in results if r["topic"] == topic]
        summary["topics"][topic] = dict(markets=len(subset), prices=dict(Counter(r["price_status"] for r in subset)),
            trades=dict(Counter(r["trade_status"] for r in subset)),
            trade_rows=sum(r["trade_rows"] for r in subset), price_points=sum(r["price_points"] for r in subset),
            shortened_windows=sum(r["shorter_than_seven_days"] for r in subset),
            explicit_anchor_fields=sum(r["anchor_source"] != "endDate_proxy" for r in subset),
            compressed_payload_bytes=sum(r["saved_payload_bytes"] for r in subset))
    if args.scope == "pilot":
        summary["pilot_markets"] = len(results)
    (OUTPUT / (prefix + "_summary.json")).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="List candidate markets by topic and month")
    inventory.add_argument("--run", type=Path, required=True)
    inventory.add_argument("--start", default="2025-09-01T00:00:00Z")
    inventory.add_argument("--end", default="2026-09-01T00:00:00Z")
    inventory.add_argument("--workers", type=int, default=6)
    inventory.add_argument("--tags", nargs="+", choices=list(TAGS), default=list(TAGS))
    inventory.set_defaults(action=collect_inventory)
    sample = commands.add_parser("collect", help="Collect metadata, trades, and prices for the saved sample")
    sample.add_argument("--workers", type=int, default=4)
    sample.add_argument("--scope", choices=("pilot", "full"), default="pilot",
                        help="Use the nested pilot or the approved full cohort (default: pilot)")
    sample.set_defaults(action=collect_sample)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    args.action(args)


if __name__ == "__main__":
    main()
