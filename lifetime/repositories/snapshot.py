"""Validate the complete data bundle before any database mutation."""

from datetime import date, datetime
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

INDICATORS = {"total": "SP.DYN.LE00.IN", "female": "SP.DYN.LE00.FE.IN", "male": "SP.DYN.LE00.MA.IN"}


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch: {path.name}")


def verify_snapshot(path):
    path = Path(path)
    if path.is_file():
        path = path.parent
    manifest = _json(path / "manifest.json")
    snapshot = _json(path / "snapshot.json")
    policy = _json(path / "entity_policy.json")
    aliases = _json(path / "legacy_aliases.json")
    if manifest["schema_version"] != 1 or snapshot["schema_version"] != 1 or policy["policy_version"] != 1:
        raise ValueError("Unsupported snapshot schema or policy")
    expected_raw = (
        {"countries.json"}
        | {f"{i}.json" for i in INDICATORS.values()}
        | {f"metadata_{i}.json" for i in INDICATORS.values()}
    )
    if set(manifest["raw_files"]) != expected_raw or set(manifest["derived_files_sha256"]) != {
        "snapshot.json",
        "legacy_aliases.json",
    }:
        raise ValueError("Incomplete manifest")
    for name, entry in manifest["raw_files"].items():
        _hash(path / "raw" / name, entry["sha256"])
    for name, digest in manifest["derived_files_sha256"].items():
        _hash(path / name, digest)
    _hash(path / "entity_policy.json", manifest["policy_sha256"])
    legacy_sources = (
        path / "legacy_input.sql",
        path.resolve().parents[1] / "db_data.sql",
        Path(__file__).resolve().parents[2] / "db_data.sql",
    )
    legacy_source = next((candidate for candidate in legacy_sources if candidate.is_file()), None)
    # Historical SQL is audit provenance, excluded from production artifacts.
    # When available in a checkout, verify its digest and original alias coverage.
    if legacy_source is not None:
        _hash(legacy_source, manifest["legacy_input_sha256"])
        sql = legacy_source.read_text(encoding="utf-8")
        block = re.search(
            r"INSERT INTO `countries` \(`id`, `type`, `alias`\) VALUES\s*(.*?);", sql, flags=re.S
        )
        if block is None:
            raise ValueError("Missing legacy geography source")
        quoted = r"'((?:\\.|''|[^'\\])*)'"
        tuple_pattern = re.compile(r"\(\s*(\d+)\s*,\s*" + quoted + r"\s*,\s*" + quoted + r"\s*\)")
        legacy_rows = tuple_pattern.findall(block[1])
        if tuple_pattern.sub("", block[1]).replace(",", "").strip():
            raise ValueError("Unparsed legacy geography source")

        def unescape(value):
            return re.sub(
                r"\\(.)",
                lambda match: {"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(match[1], match[1]),
                value.replace("''", "'"),
            )

        original_aliases = {
            (int(identifier), unescape(kind), unescape(name)) for identifier, kind, name in legacy_rows
        }
        if (
            len(original_aliases) != len(legacy_rows)
            or {(a["legacy_id"], a["legacy_type"], a["legacy_alias"]) for a in aliases} != original_aliases
        ):
            raise ValueError("Legacy mapping coverage differs from original source")
    assessment = date.fromisoformat(snapshot["assessment_date"])
    release = date.fromisoformat(snapshot["source_release_date"])
    retrieved = datetime.fromisoformat(snapshot["retrieved_at"])
    year = snapshot["common_year"]
    if (
        isinstance(year, bool)
        or not isinstance(year, int)
        or not 1900 <= year < assessment.year
        or release > assessment
        or retrieved.tzinfo is None
    ):
        raise ValueError("Invalid dataset dates")
    if not manifest["query_range"][0] <= year <= manifest["query_range"][1]:
        raise ValueError("Year outside query range")
    for key in ("assessment_date", "common_year", "source_release_date", "retrieved_at", "statistics"):
        if manifest[key] != snapshot[key]:
            raise ValueError(f"Manifest disagreement: {key}")
    if (
        snapshot["source_id"] != "world_bank_wdi"
        or snapshot["source_numeric_id"] != "2"
        or snapshot["license"] != "CC-BY-4.0"
    ):
        raise ValueError("Invalid source metadata")
    if (
        snapshot["aggregate_definition_version"] != policy["aggregate_definition_version"]
        or snapshot["default_region_codes"] != policy["default_region_codes"]
    ):
        raise ValueError("Policy disagreement")
    countries_payload = _json(path / "raw" / "countries.json")
    countries = countries_payload[1]
    _complete_payload(countries_payload)
    raw_entities = {entry["id"]: entry for entry in countries}
    source_codes = {entry["iso2Code"]: entry["id"] for entry in countries}
    entities = {entry["code"]: entry for entry in snapshot["entities"]}
    if (
        len(raw_entities) != len(countries)
        or len(source_codes) != len(countries)
        or len(entities) != len(snapshot["entities"])
        or set(entities) != set(raw_entities)
    ):
        raise ValueError("Duplicate or inconsistent geography IDs")
    for key in ("territory_codes", "non_iso_codes", "geographic_region_codes", "default_region_codes"):
        if not set(policy[key]) <= entities.keys():
            raise ValueError("Policy refers to unknown geography")
    for code, entity in entities.items():
        raw = raw_entities[code]
        aggregate = raw["region"]["id"] == "NA"
        non_iso = code in policy["non_iso_codes"]
        kind = (
            "aggregate"
            if aggregate
            else "territory"
            if code in policy["territory_codes"]
            else "area"
            if non_iso
            else "country"
        )
        aggregate_type = (
            "world"
            if code == "WLD"
            else "geographic_region"
            if code in policy["geographic_region_codes"]
            else "other_group"
            if aggregate
            else None
        )
        expected = {
            "name": raw["name"].strip(),
            "entity_type": kind,
            "aggregate_type": aggregate_type,
            "iso_alpha2": None if aggregate or non_iso else raw["iso2Code"],
            "iso_alpha3": None if aggregate or non_iso else code,
            "wb_region_code": None if aggregate else raw["region"]["id"],
            "wb_region_name": None if aggregate else raw["region"]["value"],
        }
        if not re.fullmatch(r"[A-Z0-9]{3}", code) or any(entity[k] != v for k, v in expected.items()):
            raise ValueError(f"Geography metadata mismatch: {code}")
    public = snapshot["public_entity_codes"]
    expected_public = {
        code
        for code, entry in entities.items()
        if entry["entity_type"] != "aggregate" or code in policy["default_region_codes"]
    }
    if len(set(public)) != len(public) or set(public) != expected_public:
        raise ValueError("Invalid public coverage")
    raw_observations = {}
    latest_years = {}
    for sex, indicator in INDICATORS.items():
        payload = _json(path / "raw" / f"{indicator}.json")
        _complete_payload(payload)
        if str(payload[0]["sourceid"]) != "2" or payload[0]["lastupdated"] != snapshot["source_release_date"]:
            raise ValueError("Inconsistent source release")
        metadata_payload = _json(path / "raw" / f"metadata_{indicator}.json")
        _complete_payload(metadata_payload)
        metadata = metadata_payload[1]
        if (
            len(metadata) != 1
            or metadata[0]["id"] != indicator
            or str(metadata[0]["source"]["id"]) != "2"
            or metadata[0] not in snapshot["source"]["indicators"]
        ):
            raise ValueError("Invalid indicator metadata")
        seen = set()
        available_years = []
        for row in payload[1]:
            code = row["countryiso3code"] or source_codes.get(row["country"]["id"])
            observed_year = int(row["date"])
            key = (code, observed_year)
            if (
                code not in entities
                or key in seen
                or source_codes.get(row["country"]["id"]) != code
                or row["indicator"]["id"] != indicator
            ):
                raise ValueError("Duplicate or foreign raw observation")
            seen.add(key)
            value = row["value"]
            if value is not None:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not 0 < value < 130
                    or observed_year >= assessment.year
                ):
                    raise ValueError("Invalid raw value or observation year")
                available_years.append(observed_year)
            if observed_year == year:
                raw_observations[code, sex] = row
        latest_years[sex] = max(available_years)
    if len(snapshot["observations"]) != len(entities) * 3:
        raise ValueError("Incomplete observation coverage")
    seen = set()
    missing_codes = set()
    available_count = 0
    for observation in snapshot["observations"]:
        key = (observation["entity_code"], observation["sex"])
        if key in seen or key[0] not in entities or key[1] not in INDICATORS:
            raise ValueError("Duplicate or foreign observation")
        seen.add(key)
        raw = raw_observations.get(key)
        value = raw["value"] if raw else None
        reason = None if value is not None else "source_null" if raw else "not_in_indicator_response"
        status = "available" if value is not None else "missing"
        if (
            observation["year"] != year
            or observation["indicator"] != INDICATORS[key[1]]
            or observation["value_years"] != value
            or observation["status"] != status
            or observation["missing_reason"] != reason
        ):
            raise ValueError("Observation differs from raw precision, year, or status")
        if (
            observation["source_id"] != "world_bank_wdi"
            or observation["source_release_date"] != snapshot["source_release_date"]
            or observation["retrieved_at"] != snapshot["retrieved_at"]
            or observation["estimate_type"] != "period_life_expectancy_estimate_or_projection"
        ):
            raise ValueError("Observation provenance mismatch")
        if value is not None:
            available_count += 1
        else:
            missing_codes.add(key[0])
    stats = snapshot["statistics"]
    if stats["entity_types"] != dict(Counter(entity["entity_type"] for entity in entities.values())):
        raise ValueError("Inconsistent geography coverage summary")
    if (
        stats["entities"] != len(entities)
        or stats["observations"] != len(seen)
        or stats["available"] != available_count
        or stats["missing"] != len(seen) - available_count
        or set(stats["missing_entities"]) != missing_codes
        or stats["latest_non_null_year_by_sex"] != latest_years
    ):
        raise ValueError("Inconsistent coverage summary")
    if missing_codes & set(policy["default_region_codes"]):
        raise ValueError("Missing default regional coverage")
    alias_ids, alias_names = set(), set()
    name_codes = {
        re.sub(r"[^a-z0-9]+", "-", e["name"].casefold()).strip("-"): e["code"]
        for e in entities.values()
        if e["entity_type"] != "aggregate"
    }
    for alias in aliases:
        alias_id, name = alias["legacy_id"], alias["legacy_alias"]
        if not isinstance(alias_id, int) or alias_id < 1 or alias_id in alias_ids or name in alias_names:
            raise ValueError("Duplicate legacy alias")
        alias_ids.add(alias_id)
        alias_names.add(name)
        expected = (
            policy["legacy_alias_overrides"].get(name)
            if name in policy["legacy_alias_overrides"]
            else name_codes.get(re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-"))
            if alias["legacy_type"] == "country"
            else None
        )
        if alias["target_code"] != expected or (expected is not None and expected not in entities):
            raise ValueError("Unverified legacy geography mapping")
        disposition = "mapped" if expected else "retained_unavailable"
        if alias["disposition"] != disposition or alias["status"] != (
            "mapped" if expected else "manual_review"
        ):
            raise ValueError("Invalid legacy disposition")
    # Identity includes the entire verified manifest; provider revisions with
    # the same year are preserved independently and can be reactivated.
    identity = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return identity, snapshot, manifest, aliases


def _complete_payload(payload):
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not isinstance(payload[1], list)
        or int(payload[0]["pages"]) != 1
        or int(payload[0]["total"]) != len(payload[1])
    ):
        raise ValueError("Incomplete raw API payload")
