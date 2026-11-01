
import csv
import gzip
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import pyarrow as pa
import pyarrow.parquet as pq

from audit_eda_tables import Audit, distribution, effective_cutoff
from cohort_state import validate_membership
from eda_tables import DATA, ROOT, VERSION

BASE = ROOT / "data/cohort_audit/20260914_sample200"
AUDIT = BASE / ("eda_audit_20260916" if VERSION.endswith('_v1') else "eda_audit_20260916_v2")
TYPES = {"text":pa.string(), "integer":pa.int64(), "number":pa.float64(),
         "boolean":pa.bool_(), "utc_datetime":pa.timestamp("us",tz="UTC")}
# Read column descriptions and storage rules once; calculations are below.
COLUMN_DEFINITIONS_FILE = Path(__file__).with_name("eda_columns.json")
COLUMN_DEFINITIONS = json.loads(COLUMN_DEFINITIONS_FILE.read_text(encoding="utf-8"))
PREPARATION_REVISION = "20261024_favorite_purchase_trend"


# favorite, purchase-direction and trend settings
# 5x the median
LARGE_PURCHASE_MULTIPLE = 5.0

# 24 hour trend horizon, 6 hour anchor tolarance
TREND_HOURS = 24
MAX_ANCHOR_AGE_HOURS = 6

FEATURE_PARAMETERS = {
    "large_purchase_multiple": LARGE_PURCHASE_MULTIPLE,
    "trend_hours": TREND_HOURS,
    "max_anchor_age_hours": MAX_ANCHOR_AGE_HOURS,
}
PURCHASE_KEYS = ("market_id", "wallet_address", "transaction_hash", "token_id", "side")

# format/standardize timestamps 
def utc(value):
    if isinstance(value,(int,float)):
        return datetime.fromtimestamp(value,timezone.utc)
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)

# preserve missing values as None, convert to int if stated 
def optional_number(value, as_int=False):
    return None if value in (None,"") else (int(value) if as_int else float(value))

# convery boolean 
def parse_bool(value):
    if value in (True,"True","true"):
        return True
    if value in (False,"False","false"):
        return False
    raise ValueError(f"Not an explicit Boolean: {value!r}")

# generate hash for market_id and row for dup detection 
def signature(mid,row):
    original=json.dumps(row,sort_keys=True,separators=(",",":"))
    return hashlib.sha256((mid+"|"+original).encode()).hexdigest()

# group trades by wallet 
def wallet_summary(rows):
    activity=defaultdict(float)
    for row in rows:
        activity[row["wallet_address"]]+=row["row_notional"]
    total=math.fsum(r["row_notional"] for r in rows)
    shares=sorted((value/total for value in activity.values()),reverse=True) if total>0 else []
    return dict(total=total,wallets=len(activity),top=shares[0] if shares else None,
                top5=math.fsum(shares[:5]) if shares else None,
                hhi=math.fsum(s*s for s in shares) if shares else None)

# calc grouped trade count for summary stats
def wallet_trade_summary(rows):
    groups = defaultdict(list)
    for row in rows:
        key = tuple(row[field] for field in (
            "market_id", "wallet_address", "transaction_hash", "token_id", "side"
        ))
        groups[key].append(row["row_notional"])
    totals = [math.fsum(values) for values in groups.values()]
    return {
        "wallet_trade_count": len(totals),
        "mean_wallet_trade_notional": math.fsum(totals) / len(totals) if totals else None,
    }

# prep raw api records 
def transform_trades(mid,rows,tokens,names,capture,path,digest):
    signatures=[signature(mid,row) for row in rows]
    counts=Counter(signatures); occurrences=Counter(); result=[]
    for index,(row,key) in enumerate(zip(rows,signatures)):
        oi=row["outcomeIndex"]
        if row["asset"]!=tokens[oi]:
            raise ValueError(f"Token/index mismatch: {mid}:{index}")
        occurrences[key]+=1
        result.append(dict(source_capture_id=capture,trade_row_id=f"{mid}:{digest}:{index}",market_id=mid,
            condition_id=row["conditionId"],token_id=row["asset"],wallet_address=row["proxyWallet"].lower(),
            transaction_hash=row["transactionHash"].lower(),side=row["side"],outcome_label_raw=row["outcome"],
            outcome_label=names[oi],exact_signature_id=key,trade_time_utc=utc(row["timestamp"]),
            timestamp_epoch_seconds=row["timestamp"],outcome_index=oi,
            first_outcome_direction=1 if (row["side"]=="BUY")== (oi==0) else -1,
            duplicate_group_size=counts[key],duplicate_occurrence=occurrences[key],price=row["price"],size=row["size"],
            row_notional=row["price"]*row["size"],outcome_label_changed=row["outcome"]!=names[oi],
            duplicate_candidate=counts[key]>1,duplicate_excess=occurrences[key]>1,
            in_exact_signature_sensitivity=occurrences[key]==1,source_file=path,source_file_sha256=digest,source_row_index=index))
    return sorted(result,key=lambda r:(r["timestamp_epoch_seconds"],r["source_row_index"]))

# prep price history 
def transform_prices(mid,rows,token,cutoff,capture,path,digest):
    result=[]; previous=None
    for index,row in sorted(enumerate(rows),key=lambda pair:(pair[1]["t"],pair[0])):
        gap=row["t"]-previous["t"] if previous is not None else None
        result.append(dict(source_capture_id=capture,price_row_id=f"{mid}:{digest}:{index}",market_id=mid,token_id=token,
            interval_status="first_observation" if gap is None else ("gap_over_90_minutes" if gap>5400 else "adjacent_within_90_minutes"),
            # record timestamp and probability - compute change from previous if available
            observation_time_utc=utc(row["t"]),timestamp_epoch_seconds=row["t"],probability=row["p"],
            # check cutoff gap 
            hours_before_cutoff=(cutoff-row["t"])/3600,elapsed_seconds_since_previous=gap,
            # perc point price change 
            observed_change_pp=None if previous is None else 100*(row["p"]-previous["p"]),
            gap_over_90_minutes=None if gap is None else gap>5400,gap_over_6_hours=None if gap is None else gap>21600,
            source_file=path,source_file_sha256=digest,source_row_index=index))
        previous=row
    return result

# calc certainty and movement; comapre hourly price changes 
def forecast_price_features(forecast_probability, prices):
    probability = float(forecast_probability)
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Forecast probability must be between 0 and 1.")

    usable = [
        row for row in prices
        if row["elapsed_seconds_since_previous"] is not None
        and 1800 <= row["elapsed_seconds_since_previous"] <= 5400
        and row["observed_change_pp"] is not None
    ]
    observed_hours = math.fsum(
        row["elapsed_seconds_since_previous"] for row in usable
    ) / 3600
    absolute_change = math.fsum(
        abs(row["observed_change_pp"]) for row in usable
    )

    return {
        "forecast_certainty": 2 * abs(probability - 0.5),
        "price_movement_pp_per_hour": (
            absolute_change / observed_hours if usable else None
        ),
        "usable_price_intervals": len(usable),
        "price_movement_observed_hours": observed_hours,
    }


# find favorite and confidence. exact 50/50 has no favorite but retains confidence. 
def favorite_features(forecast_probability):
    p = float(forecast_probability)
    if not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("Forecast probability must be finite and in [0, 1]")
    return {"favorite_index": None if p == .5 else int(p < .5),
            "favorite_probability": max(p, 1 - p)}

# find the large purchase direction and size relative to median 
def large_purchase_features(trades, favorite_index, multiple=LARGE_PURCHASE_MULTIPLE):

    if not math.isfinite(multiple) or multiple <= 0:
        raise ValueError("Purchase multiple must be positive and finite")
    if favorite_index not in (None, 0, 1):
        raise ValueError("Favorite index must be 0, 1 or None")
    if len({row["market_id"] for row in trades}) > 1:
        raise ValueError("Purchase features require one market at a time")
    groups, outcomes = defaultdict(list), {}
    
    #take buy trades and group by market, wallet, transaction, token, and side
    for row in trades:
        if row["side"] != "BUY":
            continue
        key = tuple(row[name] for name in PURCHASE_KEYS)
        value = float(row["row_notional"])
        outcome = row["outcome_index"]
        if not math.isfinite(value) or value < 0 or outcome not in (0, 1):
            raise ValueError("Invalid purchase value or outcome index")
        if key in outcomes and outcomes[key] != outcome:
            raise ValueError("One token group has inconsistent outcome indices")
        groups[key].append(value)
        outcomes[key] = outcome
    values = {key: math.fsum(parts) for key, parts in groups.items()}
    
    # get median of value, multiply by multiple to get threshold 
    midpoint = median(values.values()) if values else None
    threshold = multiple * midpoint if midpoint is not None else None

    # flag larage purchases 
    large = {key: value for key, value in values.items()
             if midpoint > 0 and value >= threshold}
    total = math.fsum(large.values())
    favorite_total = (math.fsum(value for key, value in large.items()
                               if outcomes[key] == favorite_index)
                      if favorite_index is not None else None)
    if not values:
        status = "no_purchases"
    elif midpoint <= 0:
        status = "nonpositive_median"
    elif not large:
        status = "no_qualifying_purchases"
    elif favorite_index is None:
        status = "no_cutoff_favorite"
    else:
        status = "available"
    return {
        "purchase_count": len(values),
        "median_purchase_value": midpoint,
        "large_threshold": threshold,
        "large_purchase_count": len(large),
        "large_purchase_value": total,
        "large_favorite_purchase_value": favorite_total,
        "large_purchase_favorite_share": favorite_total / total if status == "available" else None,
        "large_purchase_status": status,
    }

# check whether cutoff favorite has increased or decreased relative to the anchor price
def favorite_trend_features(prices, *, forecast_probability, forecast_cutoff_utc,
                            forecast_observation_utc, window_start_utc,
                            hours=TREND_HOURS, max_age_hours=MAX_ANCHOR_AGE_HOURS):
    if not isinstance(hours, int) or hours <= 0:
        raise ValueError("Trend horizon must be a positive integer number of hours")
    if not math.isfinite(max_age_hours) or not 0 <= max_age_hours < hours:
        raise ValueError("Anchor tolerance must be nonnegative and shorter than the horizon")
    favorite = favorite_features(forecast_probability)["favorite_index"]
    snapshot_age = (forecast_cutoff_utc - forecast_observation_utc).total_seconds() / 3600
    if not 0 <= snapshot_age <= max_age_hours:
        raise ValueError("Cutoff snapshot is future-dated or older than the allowed tolerance")
    target = forecast_cutoff_utc - timedelta(hours=hours)
    result = dict(trend_anchor_target=target, trend_anchor_observed=None,
                  trend_anchor_age_hours=None, trend_anchor_probability=None,
                  trend_observed_hours=None, favorite_change_pp=None, trend_status="available")
    
    # use only an observed price at or before cutoff minus hours, no more than max_age_hours old (6)
    if window_start_utc > target:
        result["trend_status"] = "history_shorter_than_horizon"
    elif not prices:
        result["trend_status"] = "no_hourly_price_history"
    else:
        eligible = [row for row in prices
                    if window_start_utc <= row["observation_time_utc"] <= target]
        if not eligible:
            result["trend_status"] = "no_price_at_or_before_anchor"
        else:
            anchor = max(eligible, key=lambda row: row["observation_time_utc"])
            observed = anchor["observation_time_utc"]
            age = (target - observed).total_seconds() / 3600
            result.update(trend_anchor_observed=observed, trend_anchor_age_hours=age)
            if age > max_age_hours:
                result["trend_status"] = "anchor_older_than_tolerance"
            else:
                p = float(anchor["probability"])
                if not math.isfinite(p) or not 0 <= p <= 1:
                    raise ValueError("Anchor probability must be finite and in [0, 1]")
                result.update(trend_anchor_probability=p,
                              trend_observed_hours=(forecast_observation_utc-observed).total_seconds()/3600)
                if favorite is None:
                    result["trend_status"] = "no_cutoff_favorite"
                else:
                    direction = 1 if favorite == 0 else -1
                    result["favorite_change_pp"] = 100 * direction * (forecast_probability - p)
    return {f"{name}_{hours}h": value for name, value in result.items()}

# collect the new feature groups 
def market_predictor_features(trades, prices, *, forecast_probability,
                              forecast_cutoff_utc, forecast_observation_utc, window_start_utc):
    if len({row["market_id"] for row in trades + prices}) > 1:
        raise ValueError("Feature inputs must belong to a single market")
    for rows, time_name in ((trades, "trade_time_utc"), (prices, "observation_time_utc")):
        if any(not window_start_utc <= row[time_name] <= forecast_cutoff_utc for row in rows):
            raise ValueError("Feature inputs fall outside the collected pre-cutoff window")
    result = favorite_features(forecast_probability)
    result.update(large_purchase_features(trades, result["favorite_index"]))
    result.update(favorite_trend_features(
        prices, forecast_probability=forecast_probability,
        forecast_cutoff_utc=forecast_cutoff_utc, forecast_observation_utc=forecast_observation_utc,
        window_start_utc=window_start_utc))
    return result


class TableWriter:
    def __init__(self,name):
        self.name=name; self.count=0
        self.columns = COLUMN_DEFINITIONS[name]
        self.schema=pa.schema([pa.field(k,TYPES[v["type"]],nullable=v["nullable"],
            metadata={key:v[key] for key in ("description", "display_label") if key in v})
            for k,v in self.columns.items()])
        self.parquet=pq.ParquetWriter(DATA/f"{name}.parquet",self.schema,compression="zstd")
        self.raw=None; self.compressed=None
        if name=="markets":
            self.csv=(DATA/"markets.csv").open("w",encoding="utf-8",newline="")
        else:
            self.raw=(DATA/f"{name}.csv.gz").open("wb")
            self.compressed=gzip.GzipFile(filename="",mode="wb",fileobj=self.raw,mtime=0)
            self.csv=io.TextIOWrapper(self.compressed,encoding="utf-8",newline="")
        self.writer=csv.DictWriter(self.csv,fieldnames=list(self.columns));self.writer.writeheader()

    def append(self,rows):
        for row in rows:
            if set(row)!=set(self.columns):
                raise ValueError(f"Schema mismatch {self.name}: {set(row)^set(self.columns)}")
            for field,spec in self.columns.items():
                if row[field] is None and not spec["nullable"]:
                    raise ValueError(f"Unexpected null: {self.name}.{field}")
        table=pa.Table.from_pylist(rows,schema=self.schema)
        if rows:self.parquet.write_table(table)
        for row in rows:
            self.writer.writerow({k:(v.isoformat().replace("+00:00","Z") if isinstance(v,datetime) else v) for k,v in row.items()})
        self.count+=len(rows)

    def close(self):
        self.parquet.close();self.csv.close()
        if self.raw:self.raw.close()

# runner 
def main():
    audited=json.loads((AUDIT/"input_manifest.json").read_text(encoding="utf-8"))["sha256"]
    for name,digest in audited.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f"Audited input changed: {name}. Re-audit and version the build.")
    reader=Audit()
    candidates=reader.csv(BASE/"active_candidates.csv","candidates")
    membership=reader.json(BASE/"cohort_membership.json")
    validate_membership(candidates,membership)
    def by_id(path):return {r["market_id"]:r for r in reader.csv(path,path.name)}
    coverage=by_id(BASE/"active_cohort_coverage.csv")
    register=by_id(BASE/"full_audit_20260915/cohort_audit_register.csv")
    options=by_id(BASE/"active_market_options.csv")
    for rows in (coverage,register,options):
        if set(rows)!=set(membership["active_market_ids"]):raise ValueError("Incomplete one-to-one metadata join")
    if (DATA/"manifest.json").exists():
        old=json.loads((DATA/"manifest.json").read_text(encoding="utf-8"))
        if old["audited_input_hashes"]!=audited:raise ValueError("Use a new build directory for changed inputs")
    DATA.mkdir(parents=True,exist_ok=True)
    writers={name:TableWriter(name) for name in COLUMN_DEFINITIONS}
    markets=[]
    try:
        for i,c in enumerate(sorted(candidates,key=lambda r:r["market_id"]),1):
            mid=c["market_id"];r=register[mid];o=options[mid]
            folder=(BASE/coverage[mid]["capture_path"]).parent
            result=reader.json(folder/"result.json"); metadata=reader.json(folder/"market.json.gz")
            original_trades=reader.json(folder/"trades_window.json.gz"); original_prices=reader.json(folder/"prices_window.json.gz")
            relative=lambda file:(folder/file).relative_to(ROOT).as_posix()
            capture=mid+":"+reader.inputs[relative("result.json")]
            tokens=json.loads(metadata["clobTokenIds"]); names=json.loads(metadata["outcomes"])
            lo,hi=result["window_start_timestamp"],result["cutoff_timestamp"]
            assert effective_cutoff(r["reviewed_anchor_utc"])==hi
            trades=transform_trades(mid,original_trades,tokens,names,capture,relative("trades_window.json.gz"),reader.inputs[relative("trades_window.json.gz")])
            prices=transform_prices(mid,original_prices,tokens[0],hi,capture,relative("prices_window.json.gz"),reader.inputs[relative("prices_window.json.gz")])
            sensitivity=[t for t in trades if t["in_exact_signature_sensitivity"]]
            ws=wallet_summary(trades);ss=wallet_summary(sensitivity)
            intervals=[p["elapsed_seconds_since_previous"] for p in prices if p["elapsed_seconds_since_previous"] is not None]
            steps=[abs(p["observed_change_pp"]) for p in prices if p["observed_change_pp"] is not None]
            probability=optional_number(c["event_inclusion_probability"])
            volume=optional_number(c["reported_volume"])
            timing=optional_number(r["timing_sensitivity_range_pp"])
            hours=(hi-lo)/3600
            m=dict(market_id=mid,condition_id=c["condition_id"],topic=c["topic"],question=c["question"],slug=c["slug"],
                event_id=o["event_id"],event_family_id=r["event_family_id"],outcome_0_token_id=tokens[0],outcome_1_token_id=tokens[1],
                outcome_0_name=names[0],outcome_1_name=names[1],event_month=r["reviewed_anchor_utc"][:7],
                event_time_utc=utc(r["reviewed_anchor_utc"]),reviewed_cutoff_utc=utc(r["reviewed_cutoff_utc"]),
                original_event_time_utc=utc(c["anchor"]),listing_time_utc=utc(c["start_date"]),closed_time_utc=utc(c["closed_time"]),
                forecast_cutoff_utc=utc(hi),window_start_utc=utc(lo),forecast_observation_utc=utc(hi-result["forecast_price_age_seconds"]),
                window_hours=hours,forecast_probability=result["forecast_probability"],
                cutoff_floor_difference_seconds=(utc(r["reviewed_cutoff_utc"])-utc(hi)).total_seconds(),
                forecast_age_seconds=result["forecast_price_age_seconds"],family_market_count=int(r["family_market_count"]),
                outcome_0_result=int(r["expected_outcome"]),forecast_price_source=result.get("cutoff_price_source") or "hourly",
                evidence_status=r["evidence_status"],boundary_type=r["boundary_type"],time_precision=r["time_precision"],
                event_source_urls=r["source_urls"],timing_sensitivity_status="reviewed_scenarios" if timing is not None else "not_evaluated_in_review",
                timing_sensitivity_range_pp=timing,short_window=hours<168,original_anchor_differs=utc(c["anchor"])!=utc(r["reviewed_anchor_utc"]),
                sampling_month_differs=c["sampling_month"]!=r["reviewed_anchor_utc"][:7],is_replacement=bool(c["replaces_market_id"]),
                collection_pilot=parse_bool(c["collection_pilot"]),sampling_month=c["sampling_month"],
                sampling_probability_status="recorded_original_design" if probability is not None else "unavailable_replacement_probability",
                replaces_market_id=c["replaces_market_id"] or None,event_inclusion_probability=probability,reported_lifetime_volume=volume,
                reported_volume_status="available_lifetime_metadata" if volume is not None else "missing_lifetime_metadata",
                event_structure=o["event_structure"],option_count_status=o["option_count_status"],
                option_count_at_cutoff=optional_number(o["option_count_at_cutoff"],True),
                listed_alternative_count_snapshot=optional_number(o["listed_alternative_count_snapshot"],True),
                alternatives_mutually_exclusive=parse_bool(o["alternatives_mutually_exclusive"]),
                contemporaneous_menu_verified=parse_bool(o["contemporaneous_menu_verified"]),trade_row_count=len(trades),
                transaction_count=len({t["transaction_hash"] for t in trades}),observed_wallet_count=ws["wallets"],
                exact_duplicate_excess=len(trades)-len(sensitivity),
                exact_duplicate_group_count=len({t["exact_signature_id"] for t in trades if t["duplicate_candidate"]}),
                sensitivity_trade_row_count=len(sensitivity),price_point_count=len(prices),price_interval_count=len(intervals),
                price_gaps_over_90_minutes=sum(g>5400 for g in intervals),price_gaps_over_6_hours=sum(g>21600 for g in intervals),
                gross_account_activity=ws["total"],sensitivity_account_activity=ss["total"],account_activity_per_observed_day=ws["total"]/(hours/24),
                mean_trade_row_size=math.fsum(t["size"] for t in trades)/len(trades) if trades else None,
                mean_trade_row_notional=ws["total"]/len(trades) if trades else None,
                top_wallet_activity_share=ws["top"],top_five_wallet_activity_share=ws["top5"],wallet_activity_hhi=ws["hhi"],
                sensitivity_top_wallet_share=ss["top"],sensitivity_wallet_hhi=ss["hhi"],
                duplicate_activity_difference_pct=100*(ws["total"]-ss["total"])/ws["total"] if ws["total"]>0 else None,
                zero_returned_trades=not trades,trade_collection_status=result["trade_status"],
                trade_summary_status="observed_rows" if trades else "no_returned_trades",
                price_path_status="observed_hourly_path" if intervals else ("single_hourly_observation" if prices else "no_hourly_observations"),
                max_price_gap_hours=max(intervals)/3600 if intervals else None,
                median_price_gap_seconds=distribution(intervals).get("median"),
                leading_price_gap_hours=(prices[0]["timestamp_epoch_seconds"]-lo)/3600 if prices else None,
                trailing_price_gap_hours=(hi-prices[-1]["timestamp_epoch_seconds"])/3600 if prices else None,
                max_observed_price_step_pp=max(steps) if steps else None,
                flat_hourly_series=len({p["probability"] for p in prices})==1 if intervals else None,
                observed_steps_ge_20pp=sum(s>=20 for s in steps) if intervals else None,
                source_capture_id=capture,source_capture_path=relative("result.json"),source_metadata_file=relative("market.json.gz"),
                source_trade_file=relative("trades_window.json.gz"),source_price_file=relative("prices_window.json.gz"),
                source_register_file=(BASE/"full_audit_20260915/cohort_audit_register.csv").relative_to(ROOT).as_posix(),
                captured_at_utc=utc(result["captured_at_utc"]))
            m.update(forecast_price_features(m["forecast_probability"], prices))
            m.update(wallet_trade_summary(trades))
            m.update(market_predictor_features(trades, prices, **{
                name: m[name] for name in ("forecast_probability", "forecast_cutoff_utc",
                                           "forecast_observation_utc", "window_start_utc")}))
            writers["trades"].append(trades);writers["price_history"].append(prices);markets.append(m)
            if i%100==0 or i==len(candidates):print(f"Built {i}/{len(candidates)} markets",flush=True)
        writers["markets"].append(markets)
    finally:
        for writer in writers.values():writer.close()
    (DATA/"schema.json").write_text(json.dumps(COLUMN_DEFINITIONS,indent=2)+"\n",encoding="utf-8")
    dictionary=["# EDA field dictionary","","Generated from the explicit builder schema. Parquet preserves types; CSV imports must use this schema.",
        "","Nulls are empty CSV cells, never a numeric zero. Times are UTC; probabilities use 0-1 units, activity uses observed price*shares.",
        "","`information_class` separates observed pre-cutoff values, derived summaries, sampling/audit annotations, later metadata, provenance and settled outcomes."]
    for table,fields in COLUMN_DEFINITIONS.items():
        dictionary.extend(["",f"## {table}","","| Field | Type | Null allowed | Meaning | Source / information class |","|---|---|---|---|---|"])
        dictionary.extend(f"| `{key}` | {s['type']} | {s['nullable']} | {s['description']} | {s['source']} / {s['information_class']} |" for key,s in fields.items())
    (DATA/"data_dictionary.md").write_text("\n".join(dictionary)+"\n",encoding="utf-8")
    for name,digest in audited.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError("Source changed during build: "+name)
    manifest=dict(version=VERSION,preparation_revision=PREPARATION_REVISION,built_at_utc=datetime.now(timezone.utc).isoformat(),
        row_counts={k:w.count for k,w in writers.items()},audited_input_hashes=audited,
        builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        column_definitions_source=COLUMN_DEFINITIONS_FILE.relative_to(ROOT).as_posix(),
        column_definitions_sha256=hashlib.sha256(COLUMN_DEFINITIONS_FILE.read_bytes()).hexdigest(),
        market_features_source="src/build_eda_tables.py",
        market_features_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        market_feature_parameters=FEATURE_PARAMETERS,
        loader_sha256=hashlib.sha256((ROOT/"src/eda_tables.py").read_bytes()).hexdigest(),
        pyarrow_version=pa.__version__,csv_null="empty cell",primary_format="parquet",source_data_unchanged=True,
        output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.iterdir() if p.suffix in (".parquet",".gz") or p.name in ("markets.csv","schema.json","data_dictionary.md")})
    (DATA/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(manifest["row_counts"]))


if __name__=="__main__":main()
