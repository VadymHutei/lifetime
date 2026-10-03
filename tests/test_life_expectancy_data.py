"""Data contract and reproducibility checks; no network or Flask dependencies."""

from collections import Counter
from datetime import date
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "life_expectancy"
SCRIPT = ROOT / "scripts" / "update_life_expectancy.py"
SPEC = importlib.util.spec_from_file_location("data_updater", SCRIPT)
UPDATER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATER)


class LifeExpectancyDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    def test_checksums_cover_retained_source_and_derived_files(self):
        for name, metadata in self.manifest["raw_files"].items():
            self.assertEqual(
                hashlib.sha256((DATA / "raw" / name).read_bytes()).hexdigest(), metadata["sha256"]
            )
        for name, digest in self.manifest["derived_files_sha256"].items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(
            hashlib.sha256((DATA / "entity_policy.json").read_bytes()).hexdigest(),
            self.manifest["policy_sha256"],
        )

    def test_one_explicit_year_and_three_observations_per_entity(self):
        entities = self.snapshot["entities"]
        codes = {e["code"] for e in entities}
        self.assertEqual(len(codes), len(entities))
        observations = self.snapshot["observations"]
        keys = {(o["entity_code"], o["year"], o["sex"]) for o in observations}
        self.assertEqual(len(keys), len(observations))
        self.assertEqual(len(observations), 3 * len(entities))
        self.assertEqual({o["year"] for o in observations}, {self.snapshot["common_year"]})
        self.assertLess(
            self.snapshot["common_year"], date.fromisoformat(self.snapshot["assessment_date"]).year
        )
        self.assertLessEqual(self.snapshot["source_release_date"], self.snapshot["assessment_date"])
        self.assertEqual({o["entity_code"] for o in observations}, codes)

    def test_null_is_explicit_and_numeric_values_keep_source_precision(self):
        for o in self.snapshot["observations"]:
            if o["status"] == "missing":
                self.assertIsNone(o["value_years"])
                self.assertIn(o["missing_reason"], {"source_null", "not_in_indicator_response"})
            else:
                self.assertTrue(math.isfinite(o["value_years"]))
                self.assertTrue(0 < o["value_years"] < 130)
                self.assertIsNone(o["missing_reason"])
        ukraine = next(
            o for o in self.snapshot["observations"] if o["entity_code"] == "UKR" and o["sex"] == "total"
        )
        source = json.loads((DATA / "raw" / "SP.DYN.LE00.IN.json").read_bytes())[1]
        raw = next(o for o in source if o["countryiso3code"] == "UKR" and int(o["date"]) == ukraine["year"])
        self.assertEqual(ukraine["value_years"], raw["value"])

    def test_entity_types_and_default_regions_are_usable(self):
        by_code = {e["code"]: e for e in self.snapshot["entities"]}
        for e in by_code.values():
            if e["entity_type"] in {"aggregate", "area"}:
                self.assertIsNone(e["iso_alpha3"])
                self.assertIsNone(e["iso_alpha2"])
        self.assertEqual(by_code["HKG"]["entity_type"], "territory")
        self.assertEqual(by_code["UKR"]["entity_type"], "country")
        self.assertEqual(by_code["XKX"]["entity_type"], "area")
        defaults = set(self.snapshot["default_region_codes"])
        self.assertTrue(all(by_code[c]["entity_type"] == "aggregate" for c in defaults))
        self.assertTrue(
            all(
                o["status"] == "available"
                for o in self.snapshot["observations"]
                if o["entity_code"] in defaults
            )
        )

    def test_summary_matches_actual_coverage(self):
        stats = self.snapshot["statistics"]
        self.assertEqual(
            dict(Counter(e["entity_type"] for e in self.snapshot["entities"])), stats["entity_types"]
        )
        self.assertEqual(
            sum(o["status"] == "available" for o in self.snapshot["observations"]), stats["available"]
        )
        self.assertEqual(
            sum(o["status"] == "missing" for o in self.snapshot["observations"]), stats["missing"]
        )

    def test_legacy_aliases_do_not_substitute_different_geographies(self):
        aliases = json.loads((DATA / "legacy_aliases.json").read_text(encoding="utf-8"))
        by_alias = {a["legacy_alias"]: a for a in aliases}
        self.assertEqual(len(by_alias), len(aliases))
        self.assertEqual(by_alias["ukraine"]["target_code"], "UKR")
        self.assertEqual(len(aliases), 188)
        self.assertEqual({a["legacy_id"] for a in aliases}, set(range(1, 189)))
        self.assertEqual(by_alias["world"]["legacy_id"], 181)
        self.assertEqual(by_alias["cote-d'ivoire"]["target_code"], "CIV")
        self.assertEqual(by_alias["people's-republic-of-china"]["target_code"], "CHN")
        for alias in ("ascension-island", "england", "south-asia", "arab-states"):
            self.assertIsNone(by_alias[alias]["target_code"])
            self.assertEqual(by_alias[alias]["status"], "manual_review")
            self.assertEqual(by_alias[alias]["disposition"], "retained_unavailable")
            self.assertIsNotNone(by_alias[alias]["unresolved_reason"])

    def test_offline_rebuild_is_byte_for_byte_reproducible(self):
        with UPDATER.temporary_workspace(ROOT) as temp:
            output = Path(temp) / "snapshot"
            shutil.copytree(DATA, output)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--offline", "--output", str(output)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for filename in ("snapshot.json", "manifest.json", "legacy_aliases.json"):
                self.assertEqual((DATA / filename).read_bytes(), (output / filename).read_bytes())
            raw_file = output / "raw" / "countries.json"
            raw_file.write_bytes(raw_file.read_bytes() + b" ")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--offline", "--output", str(output)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum mismatch", result.stderr)

    def test_future_release_and_invalid_values_are_rejected(self):
        spec = importlib.util.spec_from_file_location("data_updater", SCRIPT)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with UPDATER.temporary_workspace(ROOT) as temp:
            output = Path(temp) / "snapshot"
            shutil.copytree(DATA, output)
            with self.assertRaisesRegex(ValueError, "newer than"):
                updater.build(output, self.manifest, date(2026, 1, 1), 2024)
            raw_file = output / "raw" / "SP.DYN.LE00.IN.json"
            raw = json.loads(raw_file.read_bytes())
            next(o for o in raw[1] if o["value"] is not None)["value"] = -1
            raw_file.write_bytes(updater.json_bytes(raw))
            with self.assertRaisesRegex(ValueError, "Invalid life expectancy"):
                updater.build(output, self.manifest, date(2026, 10, 3), 2024)

    def test_failed_online_refresh_preserves_last_good_files(self):
        with UPDATER.temporary_workspace(ROOT) as temp:
            output = Path(temp) / "snapshot"
            shutil.copytree(DATA, output)
            before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            by_url = {entry["url"]: name for name, entry in self.manifest["raw_files"].items()}
            for failure in ("invalid_value", "inconsistent_release"):

                def fake_fetch(url):
                    filename = by_url[url]
                    body = (DATA / "raw" / filename).read_bytes()
                    if filename == "SP.DYN.LE00.IN.json":
                        payload = json.loads(body)
                        if failure == "invalid_value":
                            next(o for o in payload[1] if o["value"] is not None)["value"] = -100
                        else:
                            payload[0]["lastupdated"] = "2026-07-12"
                        body = UPDATER.json_bytes(payload)
                    return body, json.loads(body)

                with (
                    patch.object(UPDATER, "fetch", side_effect=fake_fetch),
                    patch.object(sys, "argv", [str(SCRIPT), "--output", str(output)]),
                ):
                    with self.assertRaises(ValueError):
                        UPDATER.main()
                after = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
                self.assertEqual(before, after)

    def test_unavailable_offline_years_preserve_existing_snapshot(self):
        for year, start_year, expected_error in (
            (2019, 2019, "outside retained query_range"),
            (2025, 2020, "no non-null coverage"),
        ):
            with self.subTest(year=year), UPDATER.temporary_workspace(ROOT) as temp:
                output = Path(temp) / "snapshot"
                shutil.copytree(DATA, output)
                before = {
                    str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()
                }
                with patch.object(
                    sys,
                    "argv",
                    [
                        str(SCRIPT),
                        "--offline",
                        "--year",
                        str(year),
                        "--start-year",
                        str(start_year),
                        "--output",
                        str(output),
                    ],
                ):
                    with self.assertRaisesRegex(ValueError, expected_error):
                        UPDATER.main()
                self.assertEqual(
                    before,
                    {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()},
                )

    def test_a_gap_in_one_indicator_is_rejected_without_replacement(self):
        with UPDATER.temporary_workspace(ROOT) as temp:
            output = Path(temp) / "snapshot"
            shutil.copytree(DATA, output)
            filename = "SP.DYN.LE00.FE.IN.json"
            raw_file = output / "raw" / filename
            raw = json.loads(raw_file.read_bytes())
            for row in raw[1]:
                if row["date"] == "2021":
                    row["value"] = None
            raw_file.write_bytes(UPDATER.json_bytes(raw))
            manifest_file = output / "manifest.json"
            manifest = json.loads(manifest_file.read_bytes())
            manifest["raw_files"][filename]["sha256"] = hashlib.sha256(raw_file.read_bytes()).hexdigest()
            manifest_file.write_bytes(UPDATER.json_bytes(manifest))
            before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            with patch.object(
                sys, "argv", [str(SCRIPT), "--offline", "--year", "2021", "--output", str(output)]
            ):
                with self.assertRaisesRegex(ValueError, "no non-null coverage for SP.DYN.LE00.FE.IN"):
                    UPDATER.main()
            self.assertEqual(
                before, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            )

    def test_unknown_policy_codes_are_rejected_without_replacement(self):
        for key in ("default_region_codes", "geographic_region_codes", "territory_codes", "non_iso_codes"):
            with self.subTest(policy_key=key), UPDATER.temporary_workspace(ROOT) as temp:
                output = Path(temp) / "snapshot"
                shutil.copytree(DATA, output)
                policy_file = output / "entity_policy.json"
                policy = json.loads(policy_file.read_bytes())
                policy[key].append("UNKNOWN_CODE")
                policy_file.write_bytes(UPDATER.json_bytes(policy))
                before = {
                    str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()
                }
                with patch.object(sys, "argv", [str(SCRIPT), "--offline", "--output", str(output)]):
                    with self.assertRaisesRegex(ValueError, "Unknown policy geography codes"):
                        UPDATER.main()
                self.assertEqual(
                    before,
                    {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()},
                )


if __name__ == "__main__":
    unittest.main()
