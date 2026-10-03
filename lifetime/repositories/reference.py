"""Transactional reference snapshots with explicit migration and activation."""

from datetime import datetime, timezone
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import insert, or_, select, update

from lifetime.services.locations import localized_name, names, public_slugs
from .schema import active_reference, dataset_versions, legacy_aliases, life_expectancy, locations
from .snapshot import verify_snapshot


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ReferenceRepository:
    def __init__(self, engine):
        self.engine = engine

    def migrate(self):
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "migrations" / "reference")
        )
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def import_snapshot(self, path):
        """Verify the whole bundle, then insert a staged revision atomically.

        Does not change the currently active revision. Identical imports are
        idempotent. Failed validation/insert leaves all prior data untouched.
        """
        dataset_id, snapshot, manifest, aliases = verify_snapshot(path)
        public = set(snapshot["public_entity_codes"])
        if not public <= names().keys():
            raise ValueError("Snapshot requires reviewed uk/en location names")
        if any(not names()[code].get(locale) for code in public for locale in ("uk", "en")):
            raise ValueError("Incomplete public localization")
        slugs = public_slugs(snapshot["entities"], aliases)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(dataset_versions.c.id).where(dataset_versions.c.id == dataset_id)
            ).scalar_one_or_none()
            if existing:
                return {
                    "id": dataset_id,
                    "dataset_id": dataset_id,
                    "imported": False,
                    "entities": len(snapshot["entities"]),
                    "observations": len(snapshot["observations"]),
                }
            meta = {key: value for key, value in snapshot.items() if key not in ("entities", "observations")}
            connection.execute(
                insert(dataset_versions).values(
                    id=dataset_id,
                    imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    common_year=snapshot["common_year"],
                    source_release_date=snapshot["source_release_date"],
                    retrieved_at=snapshot["retrieved_at"],
                    metadata_json=_json(meta),
                    manifest_json=_json(manifest),
                )
            )
            connection.execute(
                insert(locations),
                [
                    {
                        "dataset_id": dataset_id,
                        "code": entity["code"],
                        "slug": slugs[entity["code"]],
                        "name": entity["name"],
                        "entity_type": entity["entity_type"],
                        "aggregate_type": entity["aggregate_type"],
                        "public": int(entity["code"] in public),
                        "metadata_json": _json(entity),
                    }
                    for entity in snapshot["entities"]
                ],
            )
            connection.execute(
                insert(life_expectancy),
                [
                    {
                        "dataset_id": dataset_id,
                        "location_code": entry["entity_code"],
                        "year": entry["year"],
                        "sex": entry["sex"],
                        "indicator": entry["indicator"],
                        "value_years": entry["value_years"],
                        "status": entry["status"],
                        "missing_reason": entry["missing_reason"],
                        "metadata_json": _json(entry),
                    }
                    for entry in snapshot["observations"]
                ],
            )
            connection.execute(
                insert(legacy_aliases),
                [
                    {
                        "dataset_id": dataset_id,
                        "legacy_id": entry["legacy_id"],
                        "legacy_alias": entry["legacy_alias"],
                        "target_code": entry["target_code"],
                        "metadata_json": _json(entry),
                    }
                    for entry in aliases
                ],
            )
        return {
            "id": dataset_id,
            "dataset_id": dataset_id,
            "imported": True,
            "entities": len(snapshot["entities"]),
            "observations": len(snapshot["observations"]),
        }

    def activate_dataset(self, dataset_id):
        with self.engine.begin() as connection:
            if (
                connection.execute(
                    select(dataset_versions.c.id).where(dataset_versions.c.id == dataset_id)
                ).scalar_one_or_none()
                is None
            ):
                raise ValueError("unknown_dataset")
            current = connection.execute(select(active_reference.c.id)).scalar_one_or_none()
            if current is None:
                connection.execute(insert(active_reference).values(id=1, dataset_id=dataset_id))
            else:
                connection.execute(
                    update(active_reference).where(active_reference.c.id == 1).values(dataset_id=dataset_id)
                )
        return dataset_id

    def _active(self, connection):
        return (
            connection.execute(
                select(dataset_versions).join(
                    active_reference, dataset_versions.c.id == active_reference.c.dataset_id
                )
            )
            .mappings()
            .first()
        )

    def _dataset_view(self, row):
        if row is None:
            return None
        return {
            **json.loads(row["metadata_json"]),
            "id": row["id"],
            "dataset_id": row["id"],
            "imported_at": row["imported_at"],
        }

    def active_dataset(self):
        with self.engine.connect() as connection:
            return self._dataset_view(self._active(connection))

    def list_datasets(self):
        with self.engine.connect() as connection:
            return [
                self._dataset_view(row)
                for row in connection.execute(
                    select(dataset_versions).order_by(dataset_versions.c.imported_at)
                ).mappings()
            ]

    def _location_view(self, connection, row, dataset, locale, values=None):
        if values is None:
            observations = connection.execute(
                select(life_expectancy.c.sex, life_expectancy.c.value_years).where(
                    life_expectancy.c.dataset_id == dataset["id"],
                    life_expectancy.c.location_code == row["code"],
                )
            ).all()
            values = {sex: value for sex, value in observations}
        return {
            "code": row["code"],
            "slug": row["slug"],
            "name": localized_name(row["code"], row["name"], locale),
            "entity_type": row["entity_type"],
            "aggregate_type": row["aggregate_type"],
            "year": dataset["common_year"],
            "values": values,
            "dataset_id": dataset["id"],
            "available": all(values.get(sex) is not None for sex in ("total", "female", "male")),
            "source_release_date": dataset["source_release_date"],
        }

    def list_locations(self, locale="uk"):
        with self.engine.connect() as connection:
            dataset = self._active(connection)
            if dataset is None:
                return []
            rows = (
                connection.execute(
                    select(locations).where(locations.c.dataset_id == dataset["id"], locations.c.public == 1)
                )
                .mappings()
                .all()
            )
            values = {}
            for observation in connection.execute(
                select(
                    life_expectancy.c.location_code, life_expectancy.c.sex, life_expectancy.c.value_years
                ).where(life_expectancy.c.dataset_id == dataset["id"])
            ).mappings():
                values.setdefault(observation["location_code"], {})[observation["sex"]] = observation[
                    "value_years"
                ]
            result = [
                self._location_view(connection, row, dataset, locale, values.get(row["code"], {}))
                for row in rows
            ]
            return sorted(
                result,
                key=lambda item: (
                    item["code"] != "WLD",
                    item["entity_type"] != "aggregate",
                    item["name"].casefold(),
                ),
            )

    def get_location(self, identifier, locale="uk"):
        identifier = str(identifier)
        with self.engine.connect() as connection:
            dataset = self._active(connection)
            if dataset is None:
                return None
            row = (
                connection.execute(
                    select(locations).where(
                        locations.c.dataset_id == dataset["id"],
                        locations.c.public == 1,
                        or_(locations.c.code == identifier, locations.c.slug == identifier),
                    )
                )
                .mappings()
                .first()
            )
            if row:
                return self._location_view(connection, row, dataset, locale)
            return self._legacy_location(connection, identifier, dataset, locale)

    def legacy_location(self, numeric_id_or_alias, locale="uk"):
        with self.engine.connect() as connection:
            dataset = self._active(connection)
            if dataset is None:
                return None
            return self._legacy_location(connection, str(numeric_id_or_alias), dataset, locale)

    def _legacy_location(self, connection, identifier, dataset, locale):
        conditions = [legacy_aliases.c.legacy_alias == identifier]
        # Public input may contain arbitrarily long numbers. SQLite cannot
        # bind integers above int64, and Python also bounds decimal parsing.
        # Historical IDs fit a signed 32-bit integer; unknown inputs stay
        # unmatched strings instead of raising during parameter binding.
        if identifier.isascii() and identifier.isdigit() and len(identifier) <= 10:
            legacy_id = int(identifier)
            if 0 < legacy_id <= 2**31 - 1:
                conditions.append(legacy_aliases.c.legacy_id == legacy_id)
        alias = (
            connection.execute(
                select(legacy_aliases).where(legacy_aliases.c.dataset_id == dataset["id"], or_(*conditions))
            )
            .mappings()
            .first()
        )
        if alias is None:
            return None
        if alias["target_code"]:
            row = (
                connection.execute(
                    select(locations).where(
                        locations.c.dataset_id == dataset["id"], locations.c.code == alias["target_code"]
                    )
                )
                .mappings()
                .one()
            )
            return self._location_view(connection, row, dataset, locale)
        metadata = json.loads(alias["metadata_json"])
        code = f"legacy-{alias['legacy_id']}"
        return {
            "code": code,
            "slug": alias["legacy_alias"],
            "name": localized_name(code, alias["legacy_alias"], locale),
            "entity_type": metadata["legacy_type"],
            "aggregate_type": None,
            "year": dataset["common_year"],
            "values": {"total": None, "female": None, "male": None},
            "dataset_id": dataset["id"],
            "available": False,
            "source_release_date": dataset["source_release_date"],
            "unavailable_reason": metadata["unresolved_reason"],
        }
