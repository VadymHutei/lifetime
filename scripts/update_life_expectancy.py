#!/usr/bin/env python3
"""Download or rebuild a pinned World Bank WDI snapshot (standard library only)."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "life_expectancy"
INDICATORS = {"total": "SP.DYN.LE00.IN", "female": "SP.DYN.LE00.FE.IN", "male": "SP.DYN.LE00.MA.IN"}
SOURCE_ID = "2"
API = "https://api.worldbank.org/v2"


@contextmanager
def temporary_workspace(parent):
    parent = Path(parent).resolve()
    staging = parent / f"life-expectancy-staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        yield staging
    finally:
        # Bound recursive cleanup to the unique workspace we created.
        if staging.resolve().parent != parent or not staging.name.startswith("life-expectancy-staging-"):
            raise ValueError("Unsafe staging cleanup target")
        shutil.rmtree(staging)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "lifetime-data-update/2.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    payload = json.loads(body)
    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
        raise ValueError(f"Unexpected World Bank response: {url}")
    if int(payload[0]["pages"]) != 1 or int(payload[0]["total"]) != len(payload[1]):
        raise ValueError(f"Incomplete/paginated response: {url}")
    return body, payload


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def legacy_mapping(entities, policy):
    # URL aliases are authoritative in the newer root-level legacy dump.
    sql = (ROOT / "db_data.sql").read_text(encoding="utf-8")
    block = re.search(r"INSERT INTO `countries` \(`id`, `type`, `alias`\) VALUES\s*(.*?);", sql, flags=re.S)
    if block is None:
        raise ValueError("Legacy countries INSERT block not found")
    quoted = r"'((?:\\.|''|[^'\\])*)'"
    tuple_pattern = re.compile(r"\(\s*(\d+)\s*,\s*" + quoted + r"\s*,\s*" + quoted + r"\s*\)")
    pairs = tuple_pattern.findall(block[1])
    remainder = tuple_pattern.sub("", block[1]).replace(",", "").strip()
    if remainder:
        raise ValueError("Unparsed legacy country rows")

    def unescape(value):
        return re.sub(
            r"\\(.)",
            lambda match: {"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(match[1], match[1]),
            value.replace("''", "'"),
        )

    pairs = [(old_id, unescape(old_type), unescape(alias)) for old_id, old_type, alias in pairs]
    if len({p[0] for p in pairs}) != len(pairs) or len({p[2] for p in pairs}) != len(pairs):
        raise ValueError("Duplicate legacy country IDs or aliases")
    lookup = {slug(e["name"]): e["code"] for e in entities if e["entity_type"] != "aggregate"}
    overrides = policy["legacy_alias_overrides"]
    result = []
    for old_id, old_type, alias in pairs:
        code = (
            overrides.get(alias)
            if alias in overrides
            else lookup.get(slug(alias))
            if old_type == "country"
            else None
        )
        if code is not None and code not in {e["code"] for e in entities}:
            raise ValueError(f"Unknown legacy mapping target: {code}")
        result.append(
            {
                "legacy_id": int(old_id),
                "legacy_type": old_type,
                "legacy_alias": alias,
                "target_code": code,
                "status": "mapped" if code else "manual_review",
                "match": "explicit" if alias in overrides else "exact_name" if code else "none",
                "unresolved_reason": None
                if code
                else "legacy_region_boundaries_not_documented"
                if old_type == "region"
                else "no_equivalent_WDI_geography",
                "disposition": "mapped" if code else "retained_unavailable",
                "expected_http_status": 200,
            }
        )
    return result


def build(output, raw_manifest, as_of, year):
    retrieved = datetime.fromisoformat(raw_manifest["retrieved_at"])
    if retrieved.tzinfo is None:
        raise ValueError("retrieved_at requires an explicit timezone")
    query_range = raw_manifest["query_range"]
    if (
        len(query_range) != 2
        or not all(isinstance(bound, int) for bound in query_range)
        or not query_range[0] <= year <= query_range[1]
    ):
        raise ValueError(f"Selected year {year} is outside retained query_range {query_range}")
    policy = json.loads((output / "entity_policy.json").read_text(encoding="utf-8"))
    countries = json.loads((output / "raw" / "countries.json").read_bytes())[1]
    source_code_lookup = {c["iso2Code"]: c["id"] for c in countries}
    if len(source_code_lookup) != len(countries):
        raise ValueError("Ambiguous World Bank two-character codes")
    entities = []
    for c in countries:
        aggregate = c["region"]["id"] == "NA"
        non_iso = c["id"] in policy["non_iso_codes"]
        kind = (
            "aggregate"
            if aggregate
            else "territory"
            if c["id"] in policy["territory_codes"]
            else "area"
            if non_iso
            else "country"
        )
        entities.append(
            {
                "code": c["id"],
                "name": c["name"].strip(),
                "entity_type": kind,
                "aggregate_type": "world"
                if c["id"] == "WLD"
                else "geographic_region"
                if c["id"] in policy["geographic_region_codes"]
                else "other_group"
                if aggregate
                else None,
                "iso_alpha2": None if aggregate or non_iso else c["iso2Code"],
                "iso_alpha3": None if aggregate or non_iso else c["id"],
                "wb_region_code": None if aggregate else c["region"]["id"],
                "wb_region_name": None if aggregate else c["region"]["value"],
                "source_id": "world_bank_wdi",
                "classification_policy": "entity_policy.json",
            }
        )
    entities.sort(key=lambda x: x["code"])
    codes = {e["code"] for e in entities}
    if len(codes) != len(entities):
        raise ValueError("Duplicate provider geography IDs")
    for policy_key in ("default_region_codes", "geographic_region_codes", "territory_codes", "non_iso_codes"):
        unknown_codes = set(policy[policy_key]) - codes
        if unknown_codes:
            raise ValueError(f"Unknown policy geography codes in {policy_key}: {sorted(unknown_codes)}")
    if any(e["entity_type"] != "aggregate" for e in entities if e["code"] in policy["default_region_codes"]):
        raise ValueError("default_region_codes requires aggregate geographies")
    observations = []
    latest_years = {}
    release_dates = set()
    indicator_metadata = []
    for sex, indicator in INDICATORS.items():
        payload = json.loads((output / "raw" / f"{indicator}.json").read_bytes())
        if str(payload[0]["sourceid"]) != SOURCE_ID:
            raise ValueError("Unexpected source ID")
        metadata = json.loads((output / "raw" / f"metadata_{indicator}.json").read_bytes())[1]
        if (
            len(metadata) != 1
            or metadata[0]["id"] != indicator
            or str(metadata[0]["source"]["id"]) != SOURCE_ID
        ):
            raise ValueError("Unexpected indicator metadata")
        indicator_metadata.append(metadata[0])
        release = payload[0]["lastupdated"]
        if date.fromisoformat(release) > as_of:
            raise ValueError(f"API release is newer than --as-of: {release}")
        release_dates.add(release)
        by_code_year = {}
        for row in payload[1]:
            # Some WDI aggregates have an empty countryiso3code. Resolve only
            # through the provider's unique code dictionary, never by a name.
            code = row["countryiso3code"] or source_code_lookup.get(row["country"]["id"])
            observation_year = int(row["date"])
            if code not in codes:
                raise ValueError(f"Missing country metadata: {code}")
            if source_code_lookup.get(row["country"]["id"]) != code:
                raise ValueError(f"Inconsistent provider geography codes: {code}")
            if row["indicator"]["id"] != indicator:
                raise ValueError("Unexpected indicator")
            key = (code, observation_year)
            if key in by_code_year:
                raise ValueError(f"Duplicate observation: {key}")
            value = row["value"]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value < 130
            ):
                raise ValueError(f"Invalid life expectancy: {key}, {value}")
            if value is not None and observation_year >= as_of.year:
                raise ValueError(f"Non-completed/future observation year: {observation_year}")
            by_code_year[key] = row
        if not any(
            observation_year == year and row["value"] is not None
            for (_, observation_year), row in by_code_year.items()
        ):
            raise ValueError(f"Selected year {year} has no non-null coverage for {indicator}")
        latest_years[sex] = max(int(row["date"]) for row in payload[1] if row["value"] is not None)
        for entity in entities:
            row = by_code_year.get((entity["code"], year))
            value = row["value"] if row else None
            observations.append(
                {
                    "entity_code": entity["code"],
                    "year": year,
                    "sex": sex,
                    "indicator": indicator,
                    "value_years": value,
                    "status": "available" if value is not None else "missing",
                    "missing_reason": None
                    if value is not None
                    else "source_null"
                    if row
                    else "not_in_indicator_response",
                    "source_id": "world_bank_wdi",
                    "source_release_date": release,
                    "retrieved_at": raw_manifest["retrieved_at"],
                    "observation_status": row["obs_status"] if row else None,
                    "estimate_type": "period_life_expectancy_estimate_or_projection",
                }
            )
    if len(release_dates) != 1:
        raise ValueError("Inconsistent source releases across indicators; retry update")
    if year > min(latest_years.values()):
        raise ValueError("Selected common year is not available for every indicator")
    if any(
        o["status"] != "available" for o in observations if o["entity_code"] in policy["default_region_codes"]
    ):
        raise ValueError("Selected year does not cover all default public regions")
    observations.sort(key=lambda x: (x["entity_code"], x["sex"]))
    stats = {
        "entities": len(entities),
        "entity_types": dict(Counter(e["entity_type"] for e in entities)),
        "observations": len(observations),
        "available": sum(o["status"] == "available" for o in observations),
        "missing": sum(o["status"] == "missing" for o in observations),
        "latest_non_null_year_by_sex": latest_years,
        "missing_entities": [
            e["code"]
            for e in entities
            if any(o["entity_code"] == e["code"] and o["status"] == "missing" for o in observations)
        ],
    }
    snapshot = {
        "schema_version": 1,
        "assessment_date": as_of.isoformat(),
        "common_year": year,
        "retrieved_at": raw_manifest["retrieved_at"],
        "source_id": "world_bank_wdi",
        "source_numeric_id": SOURCE_ID,
        "source_release_date": next(iter(release_dates)),
        "license": "CC-BY-4.0",
        "source": {
            "id": "world_bank_wdi",
            "publisher": "World Bank",
            "dataset": "World Development Indicators",
            "api_source_id": SOURCE_ID,
            "url": "https://databank.worldbank.org/source/world-development-indicators",
            "license_url": "https://datacatalog.worldbank.org/public-licenses",
            "indicators": indicator_metadata,
        },
        "default_region_codes": policy["default_region_codes"],
        "aggregate_definition_version": policy["aggregate_definition_version"],
        "public_entity_codes": [
            e["code"]
            for e in entities
            if e["entity_type"] != "aggregate" or e["code"] in policy["default_region_codes"]
        ],
        "entities": entities,
        "observations": observations,
        "statistics": stats,
    }
    files = {
        "snapshot.json": json_bytes(snapshot),
        "legacy_aliases.json": json_bytes(legacy_mapping(entities, policy)),
    }
    for filename, body in files.items():
        (output / filename).write_bytes(body)
    manifest = {
        **raw_manifest,
        "schema_version": 1,
        "assessment_date": as_of.isoformat(),
        "common_year": year,
        "source_release_date": snapshot["source_release_date"],
        "statistics": stats,
        "derived_files_sha256": {
            filename: hashlib.sha256(body).hexdigest() for filename, body in files.items()
        },
        "policy_sha256": hashlib.sha256((output / "entity_policy.json").read_bytes()).hexdigest(),
        "legacy_input_sha256": hashlib.sha256((ROOT / "db_data.sql").read_bytes()).hexdigest(),
    }
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 3))
    parser.add_argument("--year", type=int, default=2024, help="One explicit common year; no silent fallback")
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--offline", action="store_true", help="Rebuild using retained raw responses and timestamps"
    )
    args = parser.parse_args()
    if not args.start_year <= args.year < args.as_of.year:
        parser.error("Require start-year <= year < as-of calendar year")
    if not (args.output / "entity_policy.json").is_file():
        parser.error("Output directory requires reviewed entity_policy.json")
    # Validate in a sibling staging directory. A failed build never changes the
    # last good raw/derived snapshot. Promotion requires no concurrent readers;
    # write the manifest last as the commit marker for this file bundle.
    if args.offline:
        manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
        for filename, entry in manifest["raw_files"].items():
            if hashlib.sha256((args.output / "raw" / filename).read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"Raw checksum mismatch: {filename}")
        raw_manifest = {k: manifest[k] for k in ("retrieved_at", "raw_files", "query_range")}
        downloaded = {
            filename: (args.output / "raw" / filename).read_bytes() for filename in raw_manifest["raw_files"]
        }
    else:
        urls = {"countries.json": f"{API}/country?format=json&per_page=1000"}
        for indicator in INDICATORS.values():
            query = urllib.parse.urlencode(
                {
                    "format": "json",
                    "date": f"{args.start_year}:{args.as_of.year}",
                    "per_page": 20000,
                    "source": SOURCE_ID,
                }
            )
            urls[f"{indicator}.json"] = f"{API}/country/all/indicator/{indicator}?{query}"
            urls[f"metadata_{indicator}.json"] = (
                f"{API}/indicator/{indicator}?format=json&source=2&per_page=1000"
            )
        # Fetch all before replacing any retained responses.
        downloaded = {filename: fetch(url)[0] for filename, url in urls.items()}
        raw_manifest = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "query_range": [args.start_year, args.as_of.year],
            "raw_files": {
                filename: {"url": urls[filename], "sha256": hashlib.sha256(body).hexdigest()}
                for filename, body in downloaded.items()
            },
        }
    with temporary_workspace(args.output.parent) as staging:
        shutil.copyfile(args.output / "entity_policy.json", staging / "entity_policy.json")
        (staging / "raw").mkdir()
        for filename, body in downloaded.items():
            (staging / "raw" / filename).write_bytes(body)
        stats = build(staging, raw_manifest, args.as_of, args.year)
        (args.output / "raw").mkdir(exist_ok=True)
        for filename in downloaded:
            shutil.copyfile(staging / "raw" / filename, args.output / "raw" / filename)
        for filename in ("snapshot.json", "legacy_aliases.json", "manifest.json"):
            shutil.copyfile(staging / filename, args.output / filename)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
