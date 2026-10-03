"""One release identity, available both from a checkout and an installed wheel."""

from importlib.metadata import version
from pathlib import Path
import re


def get_version():
    source = Path(__file__).resolve().parents[1] / "VERSION"
    value = source.read_text(encoding="utf-8").strip() if source.exists() else version("lifetime-service")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?", value):
        raise RuntimeError("Invalid release VERSION")
    return value
