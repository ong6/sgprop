"""Pull URA data into the store, skipping work URA hasn't published yet."""

from __future__ import annotations

import sys
from datetime import datetime

from . import schema
from .store import Store
from .ura import TRANSACTION_BATCHES, UraClient, last_publish, recent_quarters

# A batch that comes back below this share of its previous size is treated as
# a bad response, not a shrinking market: the old data is kept.
MIN_BATCH_RATIO = 0.5


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _fresh(store: Store, kind: str, need: set[str] | None = None) -> bool:
    """Synced after URA's last publish — and, for rentals, covering every
    quarter asked for (a `--quarters 2` sync must not satisfy a 12-quarter one)."""
    synced = store.meta(f"{kind}_synced_at")
    if not synced or datetime.fromisoformat(synced) < last_publish(kind):
        return False
    if need:
        have = set((store.meta(f"{kind}_quarters") or "").split(","))
        return need <= have
    return True


def sync_transactions(store: Store, client: UraClient, force: bool = False) -> dict:
    """All private residential sales, last 5 years: 4 API calls."""
    if not force and _fresh(store, "transactions"):
        _log("transactions: up to date with URA's last publish, skipped")
        return {"skipped": True}
    rows: list[schema.Transaction] = []
    counts: dict[str, int] = {}
    for batch in TRANSACTION_BATCHES:
        got = schema.transactions_from_api(client.transactions(batch))
        _log(f"transactions: batch {batch} -> {len(got):,} rows")
        prev = int(store.meta(f"transactions_batch{batch}_rows") or 0)
        if not got or (prev and len(got) < MIN_BATCH_RATIO * prev):
            # All-or-nothing: one short batch would silently drop a quarter
            # of Singapore from a full replace.
            raise RuntimeError(
                f"batch {batch} returned {len(got):,} rows (previously {prev:,}); "
                "store left untouched; retry later")
        counts[f"batch{batch}_rows"] = str(len(got))
        rows.extend(got)
    store.replace_transactions(rows)
    store.mark_synced("transactions", **counts)
    return {"rows": len(rows), "latest": max(r.month for r in rows)}


def sync_rentals(store: Store, client: UraClient, quarters: int = 12,
                 force: bool = False) -> dict:
    """Rental contracts for the last `quarters` quarters: one call per quarter."""
    wanted = recent_quarters(quarters)
    if not force and _fresh(store, "rentals", need=set(wanted)):
        _log("rentals: up to date with URA's last publish, skipped")
        return {"skipped": True}
    total, fetched = 0, []
    for q in wanted:
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
    # Only now, with every quarter in: a sync that raised above never gets here,
    # so the next run retries instead of trusting a half-refreshed store.
    covered = set((store.meta("rentals_quarters") or "").split(",")) - {""}
    store.mark_synced("rentals", quarters=",".join(sorted(covered | set(wanted))))
    return {"rows": total, "quarters": fetched}
