"""Offline tests: fixtures shaped like real URA responses, no network."""

import csv
import json
from datetime import date, datetime

import pytest

from sgprop import analysis, cli, export, listings, schema, svy21
from sgprop.store import Store
from sgprop.sync import sync_rentals, sync_transactions
from sgprop.ura import last_publish, recent_quarters

TX_API = [{
    "project": "LIVIA", "street": "PASIR RIS GROVE", "marketSegment": "OCR",
    "x": "40560.2", "y": "39055.1",
    "transaction": [
        {"area": "143", "floorRange": "11-15", "noOfUnits": "1", "contractDate": "0726",
         "typeOfSale": "3", "price": "2268888", "propertyType": "Condominium",
         "district": "18", "typeOfArea": "Strata", "tenure": "99 yrs lease commencing from 2008"},
        {"area": "143", "floorRange": "01-05", "noOfUnits": "1", "contractDate": "0826",
         "typeOfSale": "3", "price": "2080000", "propertyType": "Condominium",
         "district": "18", "typeOfArea": "Strata", "tenure": "99 yrs lease commencing from 2008"},
        {"area": "100", "floorRange": "06-10", "noOfUnits": "1", "contractDate": "0826",
         "typeOfSale": "3", "price": "1500000", "propertyType": "Condominium",
         "district": "18", "typeOfArea": "Strata", "tenure": "99 yrs lease commencing from 2008"},
    ]}, {
    "project": "LANDED HOUSING DEVELOPMENT", "street": "NEO PEE TECK LANE",
    "marketSegment": "RCR",
    "transaction": [{"area": "257", "floorRange": "-", "noOfUnits": "1", "contractDate": "0522",
                     "typeOfSale": "1", "price": "4600000", "propertyType": "Terrace",
                     "district": "05", "typeOfArea": "Land", "tenure": "Freehold"}]}]

RENT_API = [{"project": "LIVIA", "street": "PASIR RIS GROVE", "x": "40560.2", "y": "39055.1",
             "rental": [{"areaSqm": "140-150", "leaseDate": "0726", "propertyType":
                         "Non-landed Properties", "district": "18", "areaSqft": "1500-1600",
                         "noOfBedRoom": "4", "rent": 5500},
                        {"areaSqm": "140-150", "leaseDate": "0826", "propertyType":
                         "Non-landed Properties", "district": "18", "areaSqft": "1500-1600",
                         "noOfBedRoom": "4", "rent": 5300}]}]


class FakeClient:
    def __init__(self):
        self.calls = []

    def transactions(self, batch):
        self.calls.append(("tx", batch))
        return TX_API if batch == 1 else []

    def rentals(self, q):
        self.calls.append(("rent", q))
        return RENT_API if q == "26q3" else []


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.replace_transactions(schema.transactions_from_api(TX_API))
    s.replace_rentals({"2026-07", "2026-08", "2026-09"}, schema.rentals_from_api(RENT_API))
    return s


def test_normalization():
    rows = schema.transactions_from_api(TX_API)
    t = rows[0]
    assert t.month == "2026-07" and t.sale_type == "Resale"
    assert t.area_sqft == pytest.approx(1539.25, abs=0.01)
    assert t.psf == pytest.approx(2268888 / (143 * 10.764), abs=0.01)
    assert (t.freehold, t.lease_years, t.lease_start) == (False, 99, 2008)
    landed = rows[-1]
    assert landed.floor_range is None and landed.freehold and landed.lat is None


def test_svy21_origin_and_round_trip():
    lat, lon = svy21.to_latlon(38744.572, 28001.642)
    assert (lat, lon) == pytest.approx((1.366666, 103.833333), abs=1e-6)
    for p in [(1.3726, 103.9427), (1.2800, 103.8500), (1.4400, 103.7800)]:
        n, e = svy21.to_svy21(*p)
        assert svy21.to_latlon(n, e) == pytest.approx(p, abs=1e-7)


def test_comps_and_ask(store, monkeypatch):
    monkeypatch.setattr(analysis, "_months_ago", lambda n, today=None: "2024-09")
    c = analysis.comps(store, "livia", sqft=1539)
    assert c["prints"] == 2 and c["latest"]["month"] == "2026-08"
    a = analysis.ask_vs_comps(store, "LIVIA", 1539, 2_350_000)
    assert a["above_every_print"] and a["premium_vs_median_pct"] == 8.1


def test_rent_evidence(store, monkeypatch):
    monkeypatch.setattr(analysis, "_months_ago", lambda n, today=None: "2025-09")
    r = analysis.rent_evidence(store, "LIVIA", bedrooms=4)
    assert r["contracts"] == 2 and r["median_rent"] == 5400


def test_sync_skips_when_fresh_and_replaces_when_forced(tmp_path):
    s, c = Store(tmp_path / "s.db"), FakeClient()
    out = sync_transactions(s, c, force=True)
    assert out["rows"] == 4 and [x for x in c.calls if x[0] == "tx"] == [("tx", b) for b in (1, 2, 3, 4)]
    assert sync_transactions(s, c)["skipped"]           # just synced: nothing new published
    sync_transactions(s, c, force=True)
    assert s.counts()["transactions"]["rows"] == 4      # replaced, not appended


def test_sync_rentals_replaces_only_fetched_quarters(tmp_path, monkeypatch):
    import sgprop.sync as sync_mod
    monkeypatch.setattr(sync_mod, "recent_quarters", lambda n: ["26q3", "26q2"])
    s = Store(tmp_path / "s.db")
    out = sync_rentals(s, FakeClient(), force=True)
    assert out == {"rows": 2, "quarters": ["26q3"]}
    sync_rentals(s, FakeClient(), force=True)
    assert s.counts()["rentals"]["rows"] == 2


def test_export_matches_ura_csv_layout(store, tmp_path):
    p = tmp_path / "ura_district_D18.csv"
    assert export.transactions_csv(store, 18, p) == 3
    with open(p) as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == export.TX_HEADER
    r = next(r for r in rows if r["Transacted Price ($)"] == "2,268,888")
    assert r["Sale Date"] == "Jul-26" and r["Floor Level"] == "11 to 15"
    assert r["Market Segment"] == "Outside Central Region" and r["Area (SQM)"] == "143"


def test_dates_and_quarters():
    assert schema.mmyy_to_month("0526") == "2026-05"
    assert recent_quarters(3, date(2026, 2, 1)) == ["26q1", "25q4", "25q3"]
    assert last_publish("transactions", datetime(2026, 9, 24, 19)).weekday() == 1
    assert last_publish("rentals", datetime(2026, 9, 10)).date() == date(2026, 8, 15)


def test_morning_of_a_publish_day_is_not_current():
    # Tue 2026-09-22: a 09:00 sync predates that day's publish, so by 19:00 it
    # must be stale (it used to count as fresh until Friday).
    tue_evening = datetime(2026, 9, 22, 19)
    assert last_publish("transactions", tue_evening) == datetime(2026, 9, 22, 18)
    assert last_publish("transactions", datetime(2026, 9, 22, 9)) == datetime(2026, 9, 18, 18)
    assert last_publish("rentals", datetime(2026, 9, 15, 9)).date() == date(2026, 8, 15)


def test_rental_sync_that_fails_halfway_is_not_marked_current(tmp_path, monkeypatch):
    import sgprop.sync as sync_mod
    monkeypatch.setattr(sync_mod, "recent_quarters", lambda n: ["26q3", "26q2"])

    class Flaky(FakeClient):
        def rentals(self, q):
            if q == "26q2":
                raise RuntimeError("network")
            return super().rentals(q)

    s = Store(tmp_path / "s.db")
    with pytest.raises(RuntimeError):
        sync_rentals(s, Flaky(), force=True)
    assert s.meta("rentals_synced_at") is None


def test_export_reproduces_a_real_eservice_row(tmp_path):
    # From URA eservice's D19 CSV, Sep-2026:
    # CHUAN PARK,"2,066,700",828.83,"2,494",Sep-26,LORONG CHUAN,New Sale,Strata,77,"26,840",-,
    # Condominium,1,...,19,Outside Central Region,21 to 25
    api = [{"project": "CHUAN PARK", "street": "LORONG CHUAN", "marketSegment": "OCR",
            "transaction": [{"area": "77", "floorRange": "21-25", "noOfUnits": "1",
                             "contractDate": "0926", "typeOfSale": "1", "price": "2066700",
                             "propertyType": "Condominium", "district": "19",
                             "typeOfArea": "Strata", "tenure": "99 yrs lease commencing from 2024"}]},
           {"project": "X", "street": "Y", "marketSegment": "OCR",
            "transaction": [{"area": "111", "floorRange": "01-05", "noOfUnits": "1",
                             "contractDate": "0926", "typeOfSale": "3", "price": "1500000",
                             "propertyType": "Condominium", "district": "19",
                             "typeOfArea": "Strata", "tenure": "Freehold"}]}]
    s = Store(tmp_path / "e.db")
    s.replace_transactions(schema.transactions_from_api(api))
    p = tmp_path / "d19.csv"
    export.transactions_csv(s, 19, p)
    rows = {r["Project Name"]: r for r in csv.DictReader(open(p))}
    r = rows["CHUAN PARK"]
    assert (r["Transacted Price ($)"], r["Area (SQFT)"], r["Unit Price ($ PSF)"],
            r["Area (SQM)"], r["Unit Price ($ PSM)"], r["Floor Level"], r["Type of Sale"]) == \
        ("2,066,700", "828.83", "2,494", "77", "26,840", "21 to 25", "New Sale")
    assert rows["X"]["Area (SQFT)"] == "1,194.8"        # trailing zero dropped, as eservice does


def test_listings_import_persists_and_checks_against_comps(store, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(analysis, "_months_ago", lambda n, today=None: "2024-09")
    f = tmp_path / "week.csv"
    f.write_text("listing_id,project,price,sqft,bedrooms\n"
                 "a,Livia,2350000,1539,4\nb,Nowhere,1000000,900,3\n")
    assert cli.main(["--db", str(store.path), "listings", "import", str(f)]) == 0
    assert json.loads(capsys.readouterr().out) == {"source": "week", "imported": 2}
    assert cli.main(["--db", str(store.path), "listings", "check", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    livia = next(r for r in rows if r["project"] == "LIVIA")
    assert livia["prints"] == 2 and livia["above_every_print"] and livia["thin"]
    # A re-import replaces that source's snapshot rather than duplicating it.
    cli.main(["--db", str(store.path), "listings", "import", str(f)])
    assert store.counts()["listings"] == {"week": 2}


def test_listings_import_without_file_is_a_clean_error(store, capsys):
    assert cli.main(["--db", str(store.path), "listings", "import"]) == 2
    assert "needs a FILE" in capsys.readouterr().err


def test_listings_import(tmp_path):
    p = tmp_path / "mine.json"
    p.write_text(json.dumps([{"listing_id": "1", "project": "LIVIA", "price": "2,350,000",
                              "sqft": 1539, "bedrooms": 4, "district": "D18"}]))
    [l] = listings.import_file(p)
    assert l.source == "mine" and l.district == 18 and round(l.psf) == 1527


def test_cli_comps_json(store, capsys, monkeypatch):
    monkeypatch.setattr(analysis, "_months_ago", lambda n, today=None: "2024-09")
    assert cli.main(["--db", str(store.path), "comps", "LIVIA", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["prints"] == 3


def test_rental_export_matches_eservice(store, tmp_path):
    p = tmp_path / "ura_rental_D18.csv"
    assert export.rentals_csv(store, 18, p) == 2
    with open(p) as f:
        r = next(csv.DictReader(f))
    assert r["Property Type"] == "Non-Landed Properties"
    assert r["Floor Area (SQFT)"] == "1,500 to 1,600" and r["Lease Commencement Date"] == "Aug-26"
