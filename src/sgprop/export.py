"""Write the store back out in URA's own eservice CSV layout.

Tools built on the old browser download (one CSV per postal district) keep
working unchanged: point them at these files instead.
"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
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
    """Half-up, as URA rounds (1768.5039 and 1768.50 both -> '1,769');
    Python's own rounding is half-to-even."""
    q = Decimal(repr(v)).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)
    return f"{q:,.{dp}f}"


def _sqft(v: float) -> str:
    """1194.80 -> '1,194.8', 538.20 -> '538.2', 1033.34 -> '1,033.34' (eservice style)."""
    s = f"{v:,.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


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
                r["project"], _money(r["price"]), _sqft(r["area_sqft"]), _money(r["psf"]),
                _mon(r["month"]), r["street"], r["sale_type"], r["type_of_area"],
                _sqft(r["area_sqm"]),
                _money(r["price"] / r["area_sqm"]),
                _money(r["nett_price"]) if r["nett_price"] else "-",
                r["property_type"], r["units"], r["tenure"], r["district"],
                SEGMENTS.get(r["market_segment"] or "", r["market_segment"] or ""),
                _floor(r["floor_range"]),
            ])
    return len(rows)


# The eservice rental search is non-landed only, spelled with a capital L.
NON_LANDED = ("Non-landed Properties",)
_RENT_TYPE_LABEL = {"Non-landed Properties": "Non-Landed Properties"}


def _band(band: str | None) -> str:
    """'1000-1100' -> '1,000 to 1,100', as eservice writes it."""
    lo, sep, hi = (band or "").partition("-")
    if not sep or not lo.strip().isdigit() or not hi.strip().isdigit():
        return (band or "").replace("-", " to ")
    return f"{int(lo):,} to {int(hi):,}"


def rentals_csv(store: Store, district: int, path: Path,
                property_types: tuple[str, ...] = NON_LANDED) -> int:
    rows = store.query(
        "SELECT * FROM rentals WHERE district = ? AND property_type IN (%s) "
        "ORDER BY month DESC" % ",".join("?" * len(property_types)),
        (district, *property_types))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(RENT_HEADER)
        for r in rows:
            w.writerow([
                r["project"], r["street"], r["district"],
                _RENT_TYPE_LABEL.get(r["property_type"], r["property_type"]),
                r["bedrooms"] if r["bedrooms"] is not None else "NA",
                _money(r["rent"]),
                _band(r["area_sqm_band"]),
                _band(r["area_sqft_band"]),
                _mon(r["month"]),
            ])
    return len(rows)
