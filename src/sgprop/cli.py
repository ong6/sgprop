"""sgprop command line. Every command prints JSON with --json, for agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analysis, export, listings
from .store import Store


def _out(data, as_json: bool, text: str | None = None) -> None:
    if as_json or text is None:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(text)


def cmd_sync(a) -> int:
    from .sync import sync_rentals, sync_transactions
    from .ura import UraClient
    store, client = Store(a.db), UraClient()
    result = {}
    if a.what in ("all", "transactions"):
        result["transactions"] = sync_transactions(store, client, force=a.force)
    if a.what in ("all", "rentals"):
        result["rentals"] = sync_rentals(store, client, quarters=a.quarters, force=a.force)
    _out(result, True)
    return 0


def cmd_status(a) -> int:
    _out(Store(a.db).counts(), True)
    return 0


def cmd_projects(a) -> int:
    rows = analysis.find_projects(Store(a.db), a.text, limit=a.limit)
    text = "\n".join(f"{r['project']:<40} D{r['district']:02d} {r['market_segment'] or '':<3} "
                     f"{r['prints']:>5} prints, last {r['last_sale']}" for r in rows)
    _out(rows, a.json, text or "no match")
    return 0


def cmd_comps(a) -> int:
    store = Store(a.db)
    if a.ask:
        if not a.sqft:
            print("--ask needs --sqft", file=sys.stderr)
            return 2
        _out(analysis.ask_vs_comps(store, a.project, a.sqft, a.ask, months=a.months), True)
        return 0
    c = analysis.comps(store, a.project, sqft=a.sqft, months=a.months)
    if a.json:
        _out(c, True)
        return 0
    head = (f"{c['project']} · {c['prints']} prints since {c['since']}"
            + (f" · {a.sqft:.0f} sqft ±10%" if a.sqft else ""))
    if not c["prints"]:
        print(head + " — none")
        return 0
    print(f"{head}\nmedian ${c['median_psf']:,} psf (range ${c['min_psf']:,}–${c['max_psf']:,})")
    for r in c["rows"][: a.limit]:
        print(f"  {r['month']}  ${r['price']:>12,.0f}  {r['area_sqft']:>7,.0f} sqft  "
              f"${r['psf']:>6,.0f} psf  fl {r['floor_range'] or '-':<6} {r['sale_type']}")
    return 0


def cmd_rent(a) -> int:
    _out(analysis.rent_evidence(Store(a.db), a.project, bedrooms=a.beds, months=a.months), True)
    return 0


def cmd_trend(a) -> int:
    _out(analysis.psf_trend(Store(a.db), a.project), True)
    return 0


def cmd_export(a) -> int:
    store, out = Store(a.db), Path(a.out)
    districts = [int(d) for d in a.districts.split(",")] if a.districts else range(1, 29)
    written = {}
    for d in districts:
        if a.kind == "transactions":
            written[d] = export.transactions_csv(store, d, out / f"ura_district_D{d:02d}.csv")
            if a.ec:
                export.transactions_csv(store, d, out / f"ura_district_D{d:02d}_EC.csv",
                                        property_types=export.EC_TYPES)
        else:
            written[d] = export.rentals_csv(store, d, out / f"ura_rental_D{d:02d}.csv")
    _out({"dir": str(out), "rows": written}, True)
    return 0


def cmd_listings(a) -> int:
    if a.action == "adapters":
        _out(sorted(listings.adapters()), True)
        return 0
    store = Store(a.db)
    if a.action == "check":
        rows = analysis.check_listings(store, source=a.source, months=a.months)
        text = "\n".join(
            f"{r['project']:<32} {r['sqft']:>6,.0f} sqft ${r['ask_psf']:>6,} psf  "
            + (f"{r['premium_vs_median_pct']:+6.1f}% vs {r['prints']} prints"
               if r["prints"] else "no same-size prints")
            + ("  (thin)" if r["thin"] and r["prints"] else "")
            for r in rows)
        _out(rows, a.json, text or "no listings stored — run `sgprop listings import FILE`")
        return 0
    if not a.file:
        print("sgprop: listings import needs a FILE (CSV or JSON)", file=sys.stderr)
        return 2
    rows = listings.import_file(a.file)
    source = a.source or Path(a.file).stem
    for r in rows:
        r.source = source
        r.project = r.project.upper()
    store.replace_listings(source, rows)
    _out({"source": source, "imported": len(rows)}, True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sgprop", description=__doc__)
    p.add_argument("--db", help="store path (default ~/.cache/sgprop/sgprop.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="pull URA data into the local store")
    s.add_argument("what", nargs="?", default="all", choices=["all", "transactions", "rentals"])
    s.add_argument("--quarters", type=int, default=12, help="rental quarters to pull (default 12)")
    s.add_argument("--force", action="store_true", help="ignore URA's publish schedule")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("status", help="row counts, date ranges, last sync")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("projects", help="find projects by name")
    s.add_argument("text")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_projects)

    s = sub.add_parser("comps", help="a project's own recent prints")
    s.add_argument("project")
    s.add_argument("--sqft", type=float, help="narrow to this size ±10%%")
    s.add_argument("--ask", type=float, help="asking price to compare (needs --sqft)")
    s.add_argument("--months", type=int, default=24)
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_comps)

    s = sub.add_parser("rent", help="rental contracts for a project")
    s.add_argument("project")
    s.add_argument("--beds", type=int)
    s.add_argument("--months", type=int, default=12)
    s.set_defaults(fn=cmd_rent)

    s = sub.add_parser("trend", help="median psf per year for a project")
    s.add_argument("project")
    s.set_defaults(fn=cmd_trend)

    s = sub.add_parser("export", help="write URA-eservice-format CSVs per district")
    s.add_argument("kind", choices=["transactions", "rentals"])
    s.add_argument("--out", required=True)
    s.add_argument("--districts", help="e.g. 16,19,23 (default all)")
    s.add_argument("--ec", action="store_true", help="also write *_EC.csv files")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("listings", help="import your listings, check asks vs comps, list adapters")
    s.add_argument("action", choices=["import", "check", "adapters"])
    s.add_argument("file", nargs="?", help="CSV or JSON to import")
    s.add_argument("--source", help="name for this batch (default: file name)")
    s.add_argument("--months", type=int, default=24)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_listings)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except Exception as e:  # noqa: BLE001 — one clean line, not a traceback
        print(f"sgprop: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
