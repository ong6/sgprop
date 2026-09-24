"""Normalized records. URA sends strings in odd units; these are typed and clean.

Raw -> normalized rules, applied once here so every consumer agrees:

* area arrives in sqm; sqft = sqm * 10.764 and psf = price / sqft — URA's own
  factor, so sqft and psf agree with URA's published figures to the cent
* contractDate / leaseDate arrive as MMYY; stored as ``YYYY-MM``
* typeOfSale 1/2/3 -> "New Sale" / "Sub Sale" / "Resale"
* tenure is kept verbatim, plus ``lease_start`` (year) and ``freehold``
* project coordinates (SVY21) are converted to lat/lon offline
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# URA's eservice uses 10.764, not the exact 10.7639: checked on 3,000 D19
# rows, every "Area (SQFT)" and "Unit Price ($ PSF)" matches 10.764 exactly.
SQFT_PER_SQM = 10.764

SALE_TYPES = {"1": "New Sale", "2": "Sub Sale", "3": "Resale"}
SEGMENTS = {"CCR": "Core Central Region", "RCR": "Rest of Central Region",
            "OCR": "Outside Central Region"}


def mmyy_to_month(mmyy: str) -> str:
    """'0526' -> '2026-05'. URA's API data only covers the last five years."""
    s = str(mmyy).strip()
    if not re.fullmatch(r"\d{4}", s):
        raise ValueError(f"not an MMYY date: {mmyy!r}")
    return f"20{s[2:]}-{s[:2]}"


def parse_tenure(tenure: str) -> tuple[bool, int | None, int | None]:
    """(freehold, lease_years, lease_start) from URA's free-text tenure."""
    t = (tenure or "").lower()
    if "freehold" in t:
        return True, None, None
    years = re.search(r"(\d+)\s*y", t)
    start = re.search(r"(?:from|commencing from)\s*(\d{4})", t)
    return (False, int(years.group(1)) if years else None,
            int(start.group(1)) if start else None)


def _num(v) -> float | None:
    if v in (None, "", "-", "NA", "na"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


@dataclass
class Transaction:
    project: str
    street: str
    district: int
    market_segment: str | None
    property_type: str
    type_of_area: str
    sale_type: str
    month: str                      # YYYY-MM
    price: float
    nett_price: float | None
    area_sqm: float
    area_sqft: float
    psf: float
    floor_range: str | None         # '11-15', None for landed
    units: int
    tenure: str
    freehold: bool
    lease_years: int | None
    lease_start: int | None
    lat: float | None = None
    lon: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Rental:
    project: str
    street: str
    district: int
    property_type: str
    month: str                      # YYYY-MM, lease commencement
    rent: float
    bedrooms: int | None            # None for landed ('NA')
    area_sqm_band: str              # '100-150'
    area_sqft_band: str             # '1500-2000'
    area_sqft_mid: float | None     # midpoint of the band, for rough psf
    lat: float | None = None
    lon: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _band_mid(band: str) -> float | None:
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", band or "")
    return (int(m.group(1)) + int(m.group(2))) / 2 if m else None


def _coords(p: dict) -> tuple[float | None, float | None]:
    from .svy21 import to_latlon
    x, y = _num(p.get("x")), _num(p.get("y"))
    if x is None or y is None:
        return None, None
    lat, lon = to_latlon(y, x)
    return round(lat, 6), round(lon, 6)


def transactions_from_api(result: list[dict]) -> list[Transaction]:
    """Flatten PMI_Resi_Transaction's project -> transaction[] nesting."""
    out: list[Transaction] = []
    for p in result:
        lat, lon = _coords(p)
        seg = p.get("marketSegment")
        for t in p.get("transaction") or []:
            sqm = _num(t.get("area"))
            price = _num(t.get("price"))
            if not sqm or not price:
                continue
            units = int(_num(t.get("noOfUnits")) or 1)
            # Rounded first, as URA does: eservice psf is price / the 2-dp sqft
            # it prints (KOVAN REGENCY 83 sqm $1.58M -> 893.41 sqft -> $1,769).
            sqft = round(sqm * SQFT_PER_SQM, 2)
            freehold, years, start = parse_tenure(t.get("tenure", ""))
            floor = t.get("floorRange")
            out.append(Transaction(
                project=p.get("project", "").strip(),
                street=p.get("street", "").strip(),
                district=int(t.get("district") or 0),
                market_segment=seg,
                property_type=t.get("propertyType", ""),
                type_of_area=t.get("typeOfArea", ""),
                sale_type=SALE_TYPES.get(str(t.get("typeOfSale")), str(t.get("typeOfSale"))),
                month=mmyy_to_month(t["contractDate"]),
                price=price,
                nett_price=_num(t.get("nettPrice")),
                area_sqm=sqm,
                area_sqft=sqft,
                # A bulk purchase reports total price and total area, so psf
                # is still price / area.
                psf=price / sqft,         # unrounded; export rounds half-up like URA
                floor_range=None if floor in (None, "", "-") else floor,
                units=units,
                tenure=t.get("tenure", ""),
                freehold=freehold, lease_years=years, lease_start=start,
                lat=lat, lon=lon,
            ))
    return out


def rentals_from_api(result: list[dict]) -> list[Rental]:
    out: list[Rental] = []
    for p in result:
        lat, lon = _coords(p)
        for r in p.get("rental") or []:
            rent = _num(r.get("rent"))
            if not rent:
                continue
            beds = r.get("noOfBedRoom")
            out.append(Rental(
                project=p.get("project", "").strip(),
                street=p.get("street", "").strip(),
                district=int(r.get("district") or 0),
                property_type=r.get("propertyType", ""),
                month=mmyy_to_month(r["leaseDate"]),
                rent=rent,
                bedrooms=int(beds) if str(beds).isdigit() else None,
                area_sqm_band=r.get("areaSqm", ""),
                area_sqft_band=r.get("areaSqft", ""),
                area_sqft_mid=_band_mid(r.get("areaSqft", "")),
                lat=lat, lon=lon,
            ))
    return out
