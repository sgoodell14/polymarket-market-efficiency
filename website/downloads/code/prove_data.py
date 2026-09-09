"""Small, public, read-only Polymarket feasibility pull; Python standard library only.

Run: python src/prove_data.py
Each run keeps exact response bodies plus a URL/time/status manifest. This is a
bounded sample, never a claim of complete trade or wallet history.
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def json_list(value):
    return json.loads(value) if isinstance(value, str) else (value or [])


class Capture:
    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=False)
        self.requests = []

    def get(self, name, base, path, **params):
        url = base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        record = {"file": name + ".json", "url": url,
                  "fetched_at_utc": datetime.now(timezone.utc).isoformat()}
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarketEfficiencyResearch/0.1)",
            "Accept": "application/json"})
        body = b""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body, record["status"] = response.read(), response.status
                break
            except urllib.error.HTTPError as error:
                body, record["status"] = error.read(), error.code
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    record["error"] = str(error)
                    break
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == 2:
                    record["error"] = str(error)
            time.sleep(2 ** attempt)
        (self.folder / record["file"]).write_bytes(body)
        record["sha256"] = hashlib.sha256(body).hexdigest()
        self.requests.append(record)
        self.write("manifest", self.requests)
        if "error" in record:
            print(f"  WARNING {name}: {record['error']}", flush=True)
            return None
        return json.loads(body)

    def write(self, name, data):
        (self.folder / (name + ".json")).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pages(capture, prefix, path, page_size, max_pages, **params):
    rows, reason = [], "sample_cap"
    for page in range(max_pages):
        batch = capture.get(f"{prefix}_{page}", DATA, path,
                            limit=page_size, offset=page * page_size, **params)
        if not isinstance(batch, list):
            reason = "request_failed"
            break
        rows.extend(batch)
        if len(batch) < page_size:
            reason = "short_page"
            break
    return rows, {"rows": len(rows), "stop_reason": reason,
                  "full_history_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=3, choices=range(1, 11))
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    capture = Capture(ROOT / "data" / "raw" / run_id)
    end = int(time.time())  # Fixed upper bound across pagination.
    markets, trade_rows, coverage = {}, [], {}
    for category in ("politics", "sports", "crypto"):
        tag = capture.get("tag_" + category, GAMMA, "/tags/slug/" + category)
        if not tag:
            continue
        batch = capture.get("markets_" + category, GAMMA, "/markets",
                            tag_id=tag["id"], closed="true", uma_resolution_status="resolved",
                            volume_num_min=1000, limit=args.per_category,
                            order="id", ascending="false", include_tag="true")
        for market in batch or []:
            markets[market["conditionId"]] = market
        # Include one older listing per tag to exercise month-ahead price coverage.
        older = capture.get("markets_" + category + "_older", GAMMA, "/markets",
            tag_id=tag["id"], closed="true", uma_resolution_status="resolved",
            volume_num_min=1000, limit=1, order="id", ascending="false", include_tag="true",
            start_date_max=datetime.fromtimestamp(end - 45 * 86400, timezone.utc).isoformat(),
            end_date_min=datetime.fromtimestamp(end - 30 * 86400, timezone.utc).isoformat())
        for market in older or []:
            markets[market["conditionId"]] = market
    capture.write("selected_markets", list(markets.values()))
    if not markets:
        raise SystemExit("No markets retrieved; inspect the manifest. No data proof established.")
    for cid, market in markets.items():
        mid = market["id"]
        print(f"Market {mid}: {market['question']}", flush=True)
        rows, coverage[cid] = pages(capture, "trades_" + mid, "/trades", 100, 2,
                                    market=cid, takerOnly="false", end=end)
        trade_rows.extend(rows)
        tokens = json_list(market.get("clobTokenIds"))
        if tokens and market.get("closedTime"):
            anchor = int(datetime.fromisoformat(market["closedTime"].replace("Z", "+00:00")).timestamp())
            opened = datetime.fromisoformat(market["startDate"].replace("Z", "+00:00")).timestamp() if market.get("startDate") else 0
            for days in (30, 7, 1):
                target = anchor - days * 86400
                if target >= opened:
                    capture.get(f"prices_{mid}_{days}d", CLOB, "/prices-history", market=tokens[0],
                                startTs=target - 6 * 3600, endTs=target, fidelity=60)
    # Select the most frequent observed wallet so the choice is reproducible.
    wallets = Counter(row["proxyWallet"] for row in trade_rows if row.get("proxyWallet"))
    wallet = sorted(wallets, key=lambda w: (-wallets[w], w))[0] if wallets else None
    activity, activity_coverage = [], {"stop_reason": "no_wallet", "full_history_verified": False}
    if wallet:
        print(f"Wallet activity: {wallet}", flush=True)
        activity, activity_coverage = pages(capture, "wallet_activity", "/activity", 100, 2,
            user=wallet, start=1, end=end, sortBy="TIMESTAMP", sortDirection="DESC")
        # Join every observed activity market, not just the original discovery set.
        extra = sorted({r["conditionId"] for r in activity if r.get("conditionId")} - markets.keys())
        for offset in range(0, len(extra), 20):
            # Gamma defaults to open markets; query both states for wallet joins.
            for closed in ("false", "true"):
                capture.get(f"wallet_markets_{offset // 20}_{closed}", GAMMA, "/markets",
                            condition_ids=extra[offset:offset + 20], closed=closed,
                            include_tag="true", limit=100)
    capture.write("selection", {"run_id": run_id, "cutoff_timestamp": end,
        "selection_rule": "Latest IDs per politics/sports/crypto tag plus one older listing per tag; closed/resolved; volume >= 1000",
        "older_listing_rule": "startDate <= cutoff - 45 days; endDate >= cutoff - 30 days; latest ID",
        "price_rule": "First outcome token; 6-hour windows ending 30/7/1 days before closedTime; fidelity 60 minutes; skip before startDate",
        "wallet": wallet, "wallet_rule": "Most frequent wallet in sampled market trade rows",
        "market_trade_coverage": coverage, "wallet_activity_coverage": activity_coverage})
    print(f"Saved {len(markets)} markets, {len(trade_rows)} trade rows, "
          f"{len(wallets)} wallets, {len(activity)} activity rows to {capture.folder}")
    if not trade_rows or not activity:
        raise SystemExit("Partial sample only: trades or wallet activity missing; inspect manifest.")


if __name__ == "__main__":
    main()
