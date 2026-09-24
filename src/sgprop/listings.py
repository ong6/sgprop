"""Listings (asking prices) — an interface, not a scraper.

No Singapore portal offers a public listings API, and the big ones prohibit
automated collection in their terms. So sgprop ships no portal scraper.
Instead it defines what a listing looks like and how a source plugs in:

* **Import a file** you exported or collected yourself (CSV or JSON with the
  ``Listing`` fields) — ``sgprop listings import FILE`` stores it, and
  ``sgprop listings check`` prices every ask against its own format's prints.
* **Register a plugin**: any installed package can expose an adapter under
  the ``sgprop.listings`` entry-point group. It stays in your own private
  package; sgprop only discovers and calls it.

    [project.entry-points."sgprop.listings"]
    mysource = "my_pkg.adapter:MySource"

An adapter is any class with ``name`` and ``fetch(**filters) -> Iterable[Listing]``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from importlib.metadata import entry_points
from pathlib import Path
from typing import Iterable, Protocol


@dataclass
class Listing:
    source: str
    listing_id: str
    project: str
    price: float
    sqft: float
    bedrooms: int | None = None
    district: int | None = None
    floor_level: str | None = None
    tenure: str | None = None
    listed_on: str | None = None     # YYYY-MM-DD
    url: str | None = None

    @property
    def psf(self) -> float:
        return self.price / self.sqft if self.sqft else 0.0

    def to_dict(self) -> dict:
        return {**asdict(self), "psf": round(self.psf, 2)}


class ListingsAdapter(Protocol):
    name: str

    def fetch(self, **filters) -> Iterable[Listing]: ...


def adapters() -> dict[str, type]:
    """Installed adapters, by entry-point name."""
    return {ep.name: ep.load() for ep in entry_points(group="sgprop.listings")}


_FIELDS = {f.name: f for f in fields(Listing)}


def _coerce(raw: dict, source: str) -> Listing:
    data = {k: raw.get(k) for k in _FIELDS if raw.get(k) not in (None, "")}
    data.setdefault("source", source)
    for k in ("price", "sqft"):
        data[k] = float(str(data[k]).replace(",", ""))
    for k in ("bedrooms", "district"):
        if data.get(k) is not None:
            data[k] = int(str(data[k]).lstrip("Dd"))
    data["listing_id"] = str(data.get("listing_id") or f"{data['project']}:{data['price']}")
    return Listing(**data)


def import_file(path: str | Path) -> list[Listing]:
    """Load listings from a CSV or JSON file (array of objects)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text())
    else:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return [_coerce(r, source=path.stem) for r in rows]
