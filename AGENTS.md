# sgprop — agent guide

You have a local copy of Singapore's official private-residential sale and
rental records. Use it instead of browsing portals for transaction evidence.

## Before answering

1. `sgprop status`. If `transactions.synced_at` is missing or older than a
   week, run `sgprop sync` (~40 s, no browser).
2. Resolve the project's exact URA name: `sgprop projects "<fragment>"`.
   Portals and URA spell names differently ("Oasis @ Elias" vs "OASIS @ ELIAS",
   "The Centris" vs "THE CENTRIS"). Use the `project` value returned.

## The questions and the commands

| Question | Command |
|---|---|
| Is this ask above what the same format clears for? | `sgprop comps "<PROJECT>" --sqft <sqft> --ask <price>` |
| What did this size sell for, by floor, recently? | `sgprop comps "<PROJECT>" --sqft <sqft> --json` |
| What does a unit like this rent for? | `sgprop rent "<PROJECT>" --beds <n>` |
| Is the project's psf rising or flat? | `sgprop trend "<PROJECT>"` |
| Which of these listings are cheap vs their own comps? | `sgprop listings import file.csv && sgprop listings check --json` |
| Anything else | `sqlite3 ~/.cache/sgprop/sgprop.db` over `transactions` / `rentals` |

## Reading the fields

- `month` is the **contract** month (`YYYY-MM`), not the caveat date.
- `psf` is price over strata area in sqft, computed from URA's sqm. Strata area
  can include PES, terrace or aircon-ledge space, so compare a unit with prints of
  **its own size**, not a project median.
- `floor_range` is a 5-storey band (`11-15`). URA never gives a unit number, so
  treat any "same stack" claim as an inference.
- `sale_type`: `New Sale` (developer), `Sub Sale` (before completion), `Resale`.
  `comps` defaults to Resale + Sub Sale.
- Rentals give an area **band** and a bedroom count (non-landed only). Treat
  rent psf as approximate.
- A thin cohort (fewer than about 3 prints) is not evidence. Say so, and don't
  treat a median of 2 as a price.

## Don't

- Don't put the URA access key in a repo, prompt log or output.
- Don't scrape listing portals to fill gaps. Their terms prohibit it. Use
  listings the user supplies (`sgprop listings import`) or an adapter they
  installed.
