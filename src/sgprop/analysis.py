"""Questions agents and people actually ask of the data.

All pure SQL over the store, so an agent can run the same queries itself.
"""

from __future__ import annotations

import statistics
from datetime import date

from .store import Store


def _months_ago(n: int, today: date | None = None) -> str:
    today = today or date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def find_projects(store: Store, text: str, limit: int = 20) -> list[dict]:
    """Projects whose name contains `text`, with print counts and last sale."""
    return store.query(
        "SELECT project, street, district, market_segment, COUNT(*) prints, "
        "MAX(month) last_sale, ROUND(AVG(lat), 6) lat, ROUND(AVG(lon), 6) lon "
        "FROM transactions WHERE project LIKE ? GROUP BY project, street "
        "ORDER BY prints DESC LIMIT ?", (f"%{text.upper()}%", limit))


def comps(store: Store, project: str, sqft: float | None = None,
          tolerance: float = 0.10, months: int = 24,
          sale_types: tuple[str, ...] = ("Resale", "Sub Sale")) -> dict:
    """A project's own recent prints, optionally for one unit size.

    The question behind almost every listing verdict: is the ask above what
    this format actually clears for? `sqft` narrows to +/- `tolerance`.
    """
    since = _months_ago(months)
    sql = ("SELECT month, price, area_sqft, ROUND(psf, 2) psf, floor_range, sale_type FROM transactions "
           "WHERE project = ? AND month >= ? AND sale_type IN (%s)"
           % ",".join("?" * len(sale_types)))
    params: list = [project.upper(), since, *sale_types]
    if sqft:
        sql += " AND area_sqft BETWEEN ? AND ?"
        params += [sqft * (1 - tolerance), sqft * (1 + tolerance)]
    rows = store.query(sql + " ORDER BY month DESC", tuple(params))
    psfs = [r["psf"] for r in rows]
    summary = {"project": project.upper(), "since": since, "sqft": sqft,
               "prints": len(rows)}
    if psfs:
        summary.update(
            median_psf=round(statistics.median(psfs)),
            min_psf=round(min(psfs)), max_psf=round(max(psfs)),
            latest=rows[0])
    summary["rows"] = rows
    return summary


def ask_vs_comps(store: Store, project: str, sqft: float, ask_price: float,
                 months: int = 24) -> dict:
    """Where an asking price sits against the same format's own prints."""
    c = comps(store, project, sqft=sqft, months=months)
    ask_psf = ask_price / sqft
    out = {"ask_psf": round(ask_psf), "prints": c["prints"]}
    if c["prints"]:
        out.update(median_psf=c["median_psf"], max_psf=c["max_psf"],
                   premium_vs_median_pct=round((ask_psf / c["median_psf"] - 1) * 100, 1),
                   above_every_print=ask_psf > c["max_psf"])
    return out


def check_listings(store: Store, source: str | None = None,
                   months: int = 24) -> list[dict]:
    """Every stored listing against its own project's same-size prints.

    Sorted cheapest-vs-comps first: the listings worth a closer look lead.
    Listings whose project has fewer than 3 same-size prints are kept but
    flagged `thin`, since a median of two sales is not a price.
    """
    sql, params = "SELECT * FROM listings", ()
    if source:
        sql, params = sql + " WHERE source = ?", (source,)
    out = []
    for l in store.query(sql, params):
        c = ask_vs_comps(store, l["project"], l["sqft"], l["price"], months=months)
        out.append({"source": l["source"], "listing_id": l["listing_id"],
                    "project": l["project"], "bedrooms": l["bedrooms"],
                    "price": l["price"], "sqft": l["sqft"], "url": l["url"],
                    **c, "thin": c["prints"] < 3})
    return sorted(out, key=lambda r: (r["thin"], r.get("premium_vs_median_pct", 1e9)))


def rent_evidence(store: Store, project: str, bedrooms: int | None = None,
                  months: int = 12) -> dict:
    since = _months_ago(months)
    sql = "SELECT month, rent, bedrooms, area_sqft_band FROM rentals WHERE project = ? AND month >= ?"
    params: list = [project.upper(), since]
    if bedrooms is not None:
        sql += " AND bedrooms = ?"
        params.append(bedrooms)
    rows = store.query(sql + " ORDER BY month DESC", tuple(params))
    rents = [r["rent"] for r in rows]
    return {"project": project.upper(), "bedrooms": bedrooms, "since": since,
            "contracts": len(rows),
            "median_rent": round(statistics.median(rents)) if rents else None}


def psf_trend(store: Store, project: str) -> list[dict]:
    """Median psf per year for one project (resale + sub sale)."""
    rows = store.query(
        "SELECT substr(month, 1, 4) yr, psf FROM transactions WHERE project = ? "
        "AND sale_type != 'New Sale'", (project.upper(),))
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["yr"], []).append(r["psf"])
    return [{"year": y, "prints": len(v), "median_psf": round(statistics.median(v))}
            for y, v in sorted(by.items())]
