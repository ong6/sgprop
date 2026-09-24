"""Local SQLite store. One file, no server, queryable from any tool.

URA revises older records, so each sync REPLACES the dataset it covers
(all transactions; or the quarters of rentals it fetched) rather than
appending — the store always mirrors URA's current view.
"""

from __future__ import annotations

import sqlite3
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from . import config
from .schema import Rental, Transaction

_TYPES = {int: "INTEGER", float: "REAL", str: "TEXT", bool: "INTEGER"}


def _columns(cls) -> list[tuple[str, str]]:
    out = []
    for f in fields(cls):
        base = f.type.split("|")[0].strip() if isinstance(f.type, str) else f.type
        sql = {"int": "INTEGER", "float": "REAL", "str": "TEXT", "bool": "INTEGER"}.get(
            base, _TYPES.get(base, "TEXT"))
        out.append((f.name, sql))
    return out


TABLES = {"transactions": Transaction, "rentals": Rental}


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else config.data_dir() / "sgprop.db"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        for name, cls in TABLES.items():
            cols = ", ".join(f"{n} {t}" for n, t in _columns(cls))
            self.db.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS tx_project ON transactions(project)")
        self.db.execute("CREATE INDEX IF NOT EXISTS tx_district ON transactions(district, month)")
        self.db.execute("CREATE INDEX IF NOT EXISTS rent_project ON rentals(project)")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- writes ------------------------------------------------------------ #
    def _insert(self, table: str, rows: list) -> None:
        names = [n for n, _ in _columns(TABLES[table])]
        self.db.executemany(
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
            [tuple(getattr(r, n) for n in names) for r in rows])

    def replace_transactions(self, rows: list[Transaction]) -> None:
        with self.db:
            self.db.execute("DELETE FROM transactions")
            self._insert("transactions", rows)
            self._set_meta("transactions_synced_at", datetime.now().isoformat(timespec="seconds"))

    def replace_rentals(self, months: set[str], rows: list[Rental]) -> None:
        """Replace the rental rows for the given months (the quarters fetched)."""
        with self.db:
            self.db.executemany("DELETE FROM rentals WHERE month = ?", [(m,) for m in months])
            self._insert("rentals", rows)
            self._set_meta("rentals_synced_at", datetime.now().isoformat(timespec="seconds"))

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # -- reads ------------------------------------------------------------- #
    def meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, params)]

    def counts(self) -> dict:
        out = {}
        for t in TABLES:
            row = self.db.execute(
                f"SELECT COUNT(*) n, MIN(month) lo, MAX(month) hi FROM {t}").fetchone()
            out[t] = {"rows": row["n"], "from": row["lo"], "to": row["hi"],
                      "synced_at": self.meta(f"{t}_synced_at")}
        return out
