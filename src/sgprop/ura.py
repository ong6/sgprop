"""URA Data Service client.

Auth is two-step: a permanent AccessKey (free signup) buys a Token that lasts
one day. The token is cached on disk so a day of calls costs one token
request. Every service call sends both headers.

Docs: https://eservice.ura.gov.sg/maps/api/
URA asks that calls come from your own machine or server, not from an app's
end users, so don't ship a key inside a client-side product.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

from . import config

BASE = "https://eservice.ura.gov.sg/uraDataService"
TOKEN_URL = f"{BASE}/insertNewToken/v1"
SERVICE_URL = f"{BASE}/invokeUraDS/v1"
# URA's gateway rejects urllib's default agent.
USER_AGENT = "Mozilla/5.0 (sgprop; +https://github.com/ong6/sgprop)"
TRANSACTION_BATCHES = (1, 2, 3, 4)      # split by postal district, D01-D28


class UraError(RuntimeError):
    pass


def _get_json(url: str, headers: dict, timeout: float = 120, retries: int = 3) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except UnicodeDecodeError:
                # Accented project names (ENCHANTÉ) arrive as Windows-1252.
                return json.loads(raw.decode("cp1252"))
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:        # bad key / bad request: retrying won't help
                raise UraError(f"GET {url.split('?')[0]}: HTTP {e.code} {e.reason}") from e
            last = e
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise UraError(f"GET {url.split('?')[0]} failed after {retries} tries: {last}")


def recent_quarters(n: int, today: date | None = None) -> list[str]:
    """The last `n` quarters, newest first, current quarter included."""
    today = today or date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        out.append(f"{y % 100:02d}q{q}")
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


class UraClient:
    def __init__(self, access_key: str | None = None, token_cache: Path | None = None):
        self.access_key = access_key or config.credential("URA_ACCESS_KEY")
        self.token_cache = token_cache or (config.data_dir() / "ura_token.json")
        self._token: str | None = None

    # -- auth -------------------------------------------------------------- #
    def token(self) -> str:
        if self._token:
            return self._token
        today = date.today().isoformat()
        try:
            cached = json.loads(self.token_cache.read_text())
            if cached.get("date") == today and cached.get("token"):
                self._token = cached["token"]
                return self._token
        except (OSError, json.JSONDecodeError):
            pass
        data = _get_json(TOKEN_URL, {"AccessKey": self.access_key}, timeout=30)
        if data.get("Status") != "Success" or not data.get("Result"):
            raise UraError(f"token request refused: {data.get('Message') or data}")
        self._token = data["Result"]
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.token_cache, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"date": today, "token": self._token}, f)
        return self._token

    def call(self, service: str, **params) -> list[dict]:
        """Invoke one service and return its Result list."""
        qs = "&".join([f"service={service}"] + [f"{k}={v}" for k, v in params.items()])
        for attempt in (1, 2):
            data = _get_json(f"{SERVICE_URL}?{qs}",
                             {"AccessKey": self.access_key, "Token": self.token()})
            if data.get("Status") == "Success":
                return data.get("Result") or []
            msg = str(data.get("Message") or data)
            # A token that expired mid-day: drop it and ask once more.
            if attempt == 1 and "token" in msg.lower():
                self._token = None
                self.token_cache.unlink(missing_ok=True)
                continue
            raise UraError(f"{service} {params}: {msg}")
        return []

    # -- services ---------------------------------------------------------- #
    def transactions(self, batch: int) -> list[dict]:
        """Private residential sale transactions, last 5 years, one batch."""
        return self.call("PMI_Resi_Transaction", batch=batch)

    def rentals(self, ref_period: str) -> list[dict]:
        """Private residential rental contracts for one quarter, e.g. '26q2'."""
        return self.call("PMI_Resi_Rental", refPeriod=ref_period)

    def rental_medians(self) -> list[dict]:
        return self.call("PMI_Resi_Rental_Median")

    def pipeline(self) -> list[dict]:
        return self.call("PMI_Resi_Pipeline")

    def developer_sales(self, ref_period: str) -> list[dict]:
        """New-launch sales by project for one month, e.g. '0926' (MMYY)."""
        return self.call("PMI_Resi_Developer_Sales", refPeriod=ref_period)


# URA doesn't say what time of day it publishes. Treat a publish day's data as
# landing at this hour: a sync earlier that day is NOT counted as current, so
# the next sync after it re-fetches. Errs toward re-syncing, never toward
# believing a pre-publish sync is fresh.
PUBLISH_HOUR = 18


def last_publish(kind: str, now: datetime | None = None) -> datetime:
    """When URA last published `kind` ('transactions' Tue/Fri, 'rentals' the 15th).

    A sync is current only if it ran after this moment.
    """
    now = now or datetime.now()
    at = now.replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
    if kind == "transactions":
        for back in range(8):
            d = datetime.fromordinal(at.toordinal() - back).replace(hour=PUBLISH_HOUR)
            if d.weekday() in (1, 4) and d <= now:      # Tuesday, Friday
                return d
    if kind == "rentals":
        d = at.replace(day=15)
        if d > now:
            first = at.replace(day=1)
            d = datetime.fromordinal(first.toordinal() - 1).replace(day=15, hour=PUBLISH_HOUR)
        return d
    raise ValueError(kind)
