"""Write the store back out in URA's own eservice CSV layout.

Tools built on the old browser download (one CSV per postal district) keep
working unchanged: point them at these files instead.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .schema import SEGMENTS
from .store import Store

TX_HEADER = ["Project Name", "Transacted Price ($)", "Area (SQFT)", "Unit Price ($ PSF)",
             "Sale Date", "Street Name", "Type of Sale", "Type of Area", "Area (SQM)",
             "Unit Price ($ PSM)", "Nett Price($)", "Property Type", "Number of Units",
             "Tenure", "Postal District", "Market Segment", "Floor Level"]
RENT_HEADER = ["Project Name", "Street Name", "Postal District", "Property Type",
               "No of Bedroom", "Monthly Rent ($)", "Floor Area (SQM)",
               "Floor Area (SQFT)", "Lease Commencement Date"]

# The eservice district search splits condos from ECs.
CONDO_TYPES = ("Apartment", "Condominium")
EC_TYPES = ("Executive Condominium",)


def _mon(month: str) -> str:
    """'2026-05' -> 'May-26'."""
    return datetime.strptime(month, "%Y-%m").strftime("%b-%y")


def _money(v: float, dp: int = 0) -> str:
    return f"{v:,.{dp}f}"


def _floor(fr: str | None) -> str:
    return "-" if not fr else fr.replace("-", " to ")


def transactions_csv(store: Store, district: int, path: Path,
                     property_types: tuple[str, ...] = CONDO_TYPES) -> int:
    rows = store.query(
        "SELECT * FROM transactions WHERE district = ? AND property_type IN (%s) "
        "ORDER BY month DESC" % ",".join("?" * len(property_types)),
        (district, *property_types))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TX_HEADER)
        for r in rows:
            w.writerow([
                r["project"], _money(r["price"]), _money(r["area_sqft"], 2), _money(r["psf"]),
                _mon(r["month"]), r["street"], r["sale_type"], r["type_of_area"],
                _money(r["area_sqm"], 0) if float(r["area_sqm"]).is_integer()
                else _money(r["area_sqm"], 1),
                _money(r["price"] / r["area_sqm"]),
                _money(r["nett_price"]) if r["nett_price"] else "-",
                r["property_type"], r["units"], r["tenure"], r["district"],
                SEGMENTS.get(r["market_segment"] or "", r["market_segment"] or ""),
                _floor(r["floor_range"]),
            ])
    return len(rows)


def rentals_csv(store: Store, district: int, path: Path) -> int:
    rows = store.query(
        "SELECT * FROM rentals WHERE district = ? ORDER BY month DESC", (district,))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(RENT_HEADER)
        for r in rows:
            w.writerow([
                r["project"], r["street"], r["district"], r["property_type"],
                r["bedrooms"] if r["bedrooms"] is not None else "NA",
                _money(r["rent"]),
                (r["area_sqm_band"] or "").replace("-", " to "),
                (r["area_sqft_band"] or "").replace("-", " to "),
                _mon(r["month"]),
            ])
    return len(rows)
