"""Where sgprop keeps its credentials and data.

Credentials never live in a repo. Lookup order for the URA access key:

1. the ``URA_ACCESS_KEY`` environment variable
2. ``$SGPROP_CONFIG/credentials`` (default ``~/.config/sgprop/credentials``),
   a ``KEY=value`` file — create it with ``chmod 600``

Data (the SQLite store and the cached daily token) lives in ``$SGPROP_HOME``,
default ``~/.cache/sgprop``.
"""

from __future__ import annotations

import os
from pathlib import Path


class MissingCredential(RuntimeError):
    pass


def config_dir() -> Path:
    return Path(os.environ.get("SGPROP_CONFIG", "~/.config/sgprop")).expanduser()


def data_dir() -> Path:
    d = Path(os.environ.get("SGPROP_HOME", "~/.cache/sgprop")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_credentials_file() -> dict[str, str]:
    path = config_dir() / "credentials"
    out: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def credential(name: str) -> str:
    """Return a credential by name, or raise MissingCredential with a fix."""
    value = os.environ.get(name) or _read_credentials_file().get(name)
    if not value:
        raise MissingCredential(
            f"{name} is not set. Export it, or add `{name}=...` to "
            f"{config_dir() / 'credentials'} (chmod 600). A URA key is free: "
            "https://eservice.ura.gov.sg/maps/api/")
    return value
