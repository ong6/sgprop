"""Pull URA data into the store, skipping work URA hasn't published yet."""

from __future__ import annotations

import sys
from datetime import datetime

from . import schema
from .store import Store
from .ura import TRANSACTION_BATCHES, UraClient, last_publish, recent_quarters


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _fresh(store: Store, kind: str) -> bool:
    synced = store.meta(f"{kind}_synced_at")
    return bool(synced) and datetime.fromisoformat(synced) >= last_publish(kind)


def sync_transactions(store: Store, client: UraClient, force: bool = False) -> dict:
    """All private residential sales, last 5 years: 4 API calls."""
    if not force and _fresh(store, "transactions"):
        _log("transactions: up to date with URA's last publish, skipped")
        return {"skipped": True}
    rows: list[schema.Transaction] = []
    for batch in TRANSACTION_BATCHES:
        got = schema.transactions_from_api(client.transactions(batch))
        _log(f"transactions: batch {batch} -> {len(got):,} rows")
        rows.extend(got)
    if not rows:
        raise RuntimeError("URA returned no transactions; store left untouched")
    store.replace_transactions(rows)
    return {"rows": len(rows), "latest": max(r.month for r in rows)}


def sync_rentals(store: Store, client: UraClient, quarters: int = 12,
                 force: bool = False) -> dict:
    """Rental contracts for the last `quarters` quarters: one call per quarter."""
    if not force and _fresh(store, "rentals"):
        _log("rentals: up to date with URA's last publish, skipped")
        return {"skipped": True}
    total, fetched = 0, []
    for q in recent_quarters(quarters):
        got = schema.rentals_from_api(client.rentals(q))
        if not got:
            _log(f"rentals: {q} -> none published yet")
            continue
        yy, qn = int(q[:2]), int(q[3])
        months = {f"20{yy:02d}-{m:02d}" for m in range(3 * qn - 2, 3 * qn + 1)}
        store.replace_rentals(months, got)
        total += len(got)
        fetched.append(q)
        _log(f"rentals: {q} -> {len(got):,} rows")
    return {"rows": total, "quarters": fetched}
