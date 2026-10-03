"""Version-controlled names and deterministic public identifiers."""

from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata


@lru_cache(maxsize=1)
def names() -> dict:
    return json.loads(Path(__file__).with_name("location_names.json").read_text(encoding="utf-8"))


def localized_name(code: str, provider_name: str, locale: str) -> str:
    return names().get(code, {}).get(locale, provider_name)


def ascii_slug(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def public_slugs(entities: list, aliases: list) -> dict:
    # Reserve all legacy aliases, including unavailable geography pages. New
    # provider geography must never replace a similarly named legacy region.
    reserved = {a["legacy_alias"] for a in aliases}
    preferred = {}
    for alias in aliases:
        slug = alias["legacy_alias"]
        if alias["target_code"] and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            preferred.setdefault(alias["target_code"], slug)
    used = set(reserved)
    result = {}
    for entity in sorted(entities, key=lambda item: item["code"]):
        code = entity["code"]
        if code in preferred:
            slug = preferred[code]
        else:
            slug = ascii_slug(entity["name"]) or code.lower()
            if slug in used:
                slug += "-" + code.lower()
            while slug in used:
                slug += "-" + code.lower()
        used.add(slug)
        result[code] = slug
    return result
