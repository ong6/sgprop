# sgprop

Singapore private-property data from **official APIs**, in one local SQLite
file, queryable by people and AI agents. No browser, no scraping, no
dependencies beyond the Python standard library.

```bash
pip install git+https://github.com/ong6/sgprop
sgprop sync                       # every private resi sale (5 yrs) + rentals (3 yrs): ~40 s
sgprop comps "LIVIA" --sqft 1539  # a project's own recent prints for one unit size
```

```
LIVIA · 18 prints since 2024-09 · 1539 sqft ±10%
median $1,361 psf (range $1,172–$1,474)
  2026-08  $   2,200,000    1,539 sqft  $ 1,429 psf  fl 01-05  Resale
  2026-08  $   2,180,000    1,539 sqft  $ 1,416 psf  fl 06-10  Resale
  ...
```

## Why

Most Singapore property tools drive a browser through URA's eservice pages,
one district at a time. URA publishes the same data through a free API
(official, licensed for reuse). A full sync takes one token request and 16
calls: four for transactions, one per rental quarter.

| Data | Source | Refresh |
|---|---|---|
| Sale transactions: price, area, psf, floor range, tenure, sale type, 5 yrs | URA `PMI_Resi_Transaction` | Tue & Fri |
| Rental contracts: rent, bedrooms, area band | URA `PMI_Resi_Rental` | 15th monthly |
| Project coordinates | URA (SVY21), converted to lat/lon offline | with the above |

`sgprop sync` checks URA's publish schedule (sales Tue/Fri, rentals the 15th,
counted from 18:00) and does nothing if the store is already current
(`--force` overrides). A sync that fails partway is never recorded as current. URA revises older records, so each sync
replaces what it fetched instead of appending.

## Setup

1. Get a free URA access key: <https://eservice.ura.gov.sg/maps/api/>
2. Put it outside any repo:

   ```bash
   mkdir -p ~/.config/sgprop && chmod 700 ~/.config/sgprop
   echo 'URA_ACCESS_KEY=your-key' > ~/.config/sgprop/credentials
   chmod 600 ~/.config/sgprop/credentials
   ```

   or `export URA_ACCESS_KEY=...`. The daily token is fetched and cached for you.

Data lives in `~/.cache/sgprop/sgprop.db` (`SGPROP_HOME` or `--db` to move it).

## Commands

| Command | What it answers |
|---|---|
| `sgprop sync [transactions\|rentals] [--quarters 12]` | pull or refresh from URA |
| `sgprop status` | rows, date range, last sync |
| `sgprop projects TEXT` | find a project's exact URA name |
| `sgprop comps PROJECT [--sqft N] [--months 24]` | its own recent prints, optionally one size ±10% |
| `sgprop comps PROJECT --sqft N --ask PRICE` | is this ask above what the format clears for? |
| `sgprop rent PROJECT [--beds 3]` | median rent and contract count |
| `sgprop trend PROJECT` | median psf per year |
| `sgprop export transactions\|rentals --out DIR [--ec]` | URA-eservice-format CSVs per district, byte-compatible with the old download (`--ec` adds `*_EC.csv`) |
| `sgprop listings import FILE [--source NAME]` | store your own listings (CSV/JSON); a re-import replaces that source |
| `sgprop listings check` | every stored ask vs its own format's prints, cheapest first |
| `sgprop listings adapters` | installed listing plugins |

Add `--json` to `projects`, `comps` and `listings check` for machine-readable
output (the other commands always print JSON). For anything else, the store is plain SQLite:
`sqlite3 ~/.cache/sgprop/sgprop.db "SELECT ..."`.

## Listings (asking prices)

No Singapore portal has a public listings API, and the major portals'
terms prohibit automated collection. **sgprop ships no portal scraper.** It
defines a `Listing` record and a plugin hook instead:

- import a file you collected yourself, then price it: `sgprop listings import mine.csv &&
  sgprop listings check`. Columns: `project, price, sqft` required; `listing_id,
  bedrooms, district, floor_level, tenure, listed_on, url` optional.
- or install your own adapter, exposed under the `sgprop.listings` entry point:

  ```toml
  [project.entry-points."sgprop.listings"]
  mysource = "my_pkg.adapter:MySource"   # has .name and .fetch(**filters) -> Iterable[Listing]
  ```

Whatever you plug in, its terms of use are yours to respect.

## Development

```bash
git clone https://github.com/ong6/sgprop && cd sgprop
python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest -q
```

Tests are offline. CI runs them on Python 3.10–3.13.

## For agents

See [AGENTS.md](AGENTS.md): what to run, and what each field means.

## Data licence

Contains information from URA's Data Service, made available under the
[Singapore Open Data Licence](https://data.gov.sg/open-data-licence) and
[URA API terms](https://www.ura.gov.sg/eservices-info/maps/api-terms-of-service/).
URA asks that calls come from your own machine or server, not from an app's
end users. Code is MIT.
