"""Select 200 candidates/topic and a nested 20/topic collection pilot offline."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "data/cohort_audit/20260914_inventory"
OUTPUT = ROOT / "data/cohort_audit/20260914_sample200"
CORE = {"Sports": "game_winner", "Politics": "elections", "Economics": "macro_policy"}
SEED = "efficiency-200-v1"


def active_candidates(rows):
    """Apply exclusions and audited replacements, preserving the original draw."""
    manifest_path = OUTPUT / 'cohort_membership.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')).get('one_contract_per_event_family'):
        raise RuntimeError('Historical draw reconstruction cannot overwrite the family-unique cohort. Read active_candidates.csv and validate cohort_membership.json instead.')
    path = ROOT / "docs/approved_cohort_decisions.json"
    decisions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    excluded = {str(r["market_id"]) for r in decisions.get("exclusions", [])}
    result = [dict(r) for r in rows if r["market_id"] not in excluded]
    input_ids = {r["market_id"] for r in rows}
    replacement_path = OUTPUT / "replacement_candidates.csv"
    if replacement_path.exists():
        with replacement_path.open(encoding="utf-8", newline="") as handle:
            replacements = {r["market_id"]: r for r in csv.DictReader(handle)}
        for replacement in decisions.get("replacements", []):
            if replacement["excluded_market_id"] in input_ids:
                row = replacements[replacement["replacement_market_id"]]
                if row["market_id"] not in {r["market_id"] for r in result}:
                    result.append(dict(row))
    omitted = {str(r['market_id']) for r in decisions.get('omissions_without_replacement', [])}
    return [r for r in result if r['market_id'] not in omitted]


def hashed(value):
    return hashlib.sha256((SEED + ":" + value).encode()).hexdigest()


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def event_groups(rows):
    # Connected components prevent A;B and B;C from entering separately.
    parent = {}

    def root(event):
        parent.setdefault(event, event)
        if parent[event] != event:
            parent[event] = root(parent[event])
        return parent[event]

    for row in rows:
        ids = row["event_ids"].split(";") if row["event_ids"] else ["market:" + row["market_id"]]
        for event in ids[1:]:
            parent[root(event)] = root(ids[0])
        root(ids[0])
    grouped = defaultdict(list)
    for row in rows:
        first = row["event_ids"].split(";")[0] or "market:" + row["market_id"]
        grouped[root(first)].append(row)
    return list(grouped.values())


def ordered(rows, label):
    buckets = defaultdict(list)
    for row in rows:
        buckets[row["sampling_month"]].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda r: hashed(label + ":" + r["sampling_event_key"]))
    # Shuffle the month order too; a partial cycle must not favor early months.
    months = sorted(buckets, key=lambda month: hashed(label + ":month:" + month))
    index = 0
    while any(index < len(bucket) for bucket in buckets.values()):
        for month in months:
            if index < len(buckets[month]):
                yield buckets[month][index]
        index += 1


def main():
    if (OUTPUT / 'cohort_membership.json').exists():
        raise RuntimeError('The cohort has approved omissions. Original sampling is historical; do not overwrite the audited roster. See docs/data_process_walkthrough.md.')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assert json.loads((CURRENT / "inventory_summary.json").read_text())["pagination_complete"]
    with (CURRENT / "candidate_inventory.csv").open(encoding="utf-8", newline="") as handle:
        current = [r for r in csv.DictReader(handle) if r["subtype"] == CORE[r["topic"]]]
    current = [r for r in current if r["candidate_24h"] == "True" and r["is_mention"] == "False"]
    primary, pilot, reserves, summary = [], [], [], {}
    for topic in CORE:
        representatives = []
        for members in event_groups([r for r in current if r["topic"] == topic]):
            if topic == "Sports":
                if len(members) > 3:
                    continue
                members = [r for r in members if "games" in r["tag_slugs"].split(";")
                           and "golf" not in r["tag_slugs"].split(";")
                           and r["anchor_source"] != "endDate_proxy"]
            if not members:
                continue
            event_key = ";".join(sorted({e for r in members for e in r["event_ids"].split(";") if e}))
            event_key = event_key or "market:" + members[0]["market_id"]
            # Independent hash selects one eligible contract inside each event.
            row = dict(min(members, key=lambda r: hashed("contract:" + r["market_id"])))
            row.update(sampling_event_key=event_key,
                       sampling_month=min(r["end_date"][:7] for r in members),
                       eligible_contracts_in_event=len(members),
                       validation_status="pending_topic_rules_event_time_and_history_review")
            representatives.append(row)
        ranked = list(ordered(representatives, "primary:" + topic))
        assert len(ranked) >= 200, (topic, len(ranked))
        chosen = ranked[:200]
        pilot_ids = {r["market_id"] for r in list(ordered(chosen, "pilot:" + topic))[:20]}
        month_pool = Counter(r["sampling_month"] for r in ranked)
        month_sample = Counter(r["sampling_month"] for r in chosen)
        for rank, row in enumerate(ranked, 1):
            month = row["sampling_month"]
            row.update(selection_rank=rank, cohort_role="primary" if rank <= 200 else "reserve",
                       collection_pilot=row["market_id"] in pilot_ids,
                       month_event_pool=month_pool[month], month_event_sample=month_sample[month],
                       event_inclusion_probability=month_sample[month] / month_pool[month])
        primary.extend(chosen)
        pilot.extend(r for r in chosen if r["market_id"] in pilot_ids)
        reserves.extend(ranked[200:])
        summary[topic] = {"eligible_event_groups": len(ranked), "selected": 200, "pilot": 20,
                          "selected_by_month": dict(sorted(month_sample.items())),
                          "explicit_time_fields": sum(r["anchor_source"] != "endDate_proxy" for r in chosen)}
    assert len({r["market_id"] for r in primary}) == 600
    write_csv(OUTPUT / "primary_candidates.csv", primary)
    write_csv(OUTPUT / "pilot_candidates.csv", pilot)
    write_csv(OUTPUT / "active_candidates.csv", active_candidates(primary))
    write_csv(OUTPUT / "active_pilot_candidates.csv", active_candidates(pilot))
    write_csv(OUTPUT / "reserve_candidates.csv", reserves)
    # Keep researcher-entered review fields across reproducible selection reruns.
    queue_path = OUTPUT / "validation_queue.csv"
    previous = {}
    if queue_path.exists():
        with queue_path.open(encoding="utf-8", newline="") as handle:
            previous = {r["market_id"]: r for r in csv.DictReader(handle)}
    queue = []
    original_ids = {r["market_id"] for r in primary}
    queue_candidates = primary + [r for r in active_candidates(primary) if r["market_id"] not in original_ids]
    for row in queue_candidates:
        review = dict(topic=row["topic"], market_id=row["market_id"], question=row["question"],
                      event_ids=row["event_ids"], collection_pilot=row["collection_pilot"],
                      provisional_anchor=row["anchor"], anchor_source=row["anchor_source"],
                      market_metadata_url="https://gamma-api.polymarket.com/markets/" + row["market_id"],
                      event_family_id="", reviewed_topic_subtype="", verified_event_time_utc="",
                      event_time_source_url="", review_status="pending", review_notes="")
        for field in ("event_family_id", "reviewed_topic_subtype", "verified_event_time_utc",
                      "event_time_source_url", "review_status", "review_notes"):
            review[field] = previous.get(row["market_id"], {}).get(field, review[field])
        queue.append(review)
    write_csv(queue_path, queue)
    manifest = dict(seed=SEED, status="600_candidates_selected_60_pilot_candidates",
                    scheduled_end_window="2025-09-01 <= endDate < 2026-09-01", topics=summary,
                    design="Month-balanced event sampling; one hashed random contract per event; nested month-balanced pilot.",
                    forecast_hours=24, feature_window_days=7, price_fidelity_minutes=60,
                    exclusions="Mentions excluded. Sports: games tag, no golf, <=3 eligible contracts/event, explicit start.",
                    limitations=["Topic tags and event times are provisional; this is not a validated cohort.",
                                 "Event groups may still share an underlying event family.",
                                 "Month-balanced sampling is not a uniform sample of all contracts.",
                                 "No volume or realized accuracy filtering. Prior-year data is not used.",
                                 "Reserve rank is for logged quality exclusions; no automatic replacements."])
    (OUTPUT / "selection_summary.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
