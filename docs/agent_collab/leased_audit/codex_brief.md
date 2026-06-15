# Codex audit request — "Leased %" / occupancy logic (READ-ONLY)

You are a **read-only auditor**. Do NOT modify any files or propose patches to
apply — just report findings. Claude is the sole writer.

## What to audit
The dashboard's **"Leased %" (occupancy)** metric and confirm it's applied
**consistently to all comps**.

Intended semantics (confirmed by the owner, a leasing broker):
- Occupancy is derived from **projected availability dates**. A unit that is
  *listed as available* is **not necessarily vacant** — a future move-in date
  means the current tenant gave notice but is **still occupied today**, so it
  counts as leased.
- Only **near-term** availability (within ~7 days, via `is_vacant()`) reduces
  occupancy: `leased = (total - vacant_within_7d) / total`.

## Where it lives
- `src/dashboard/_helpers.py` → `is_vacant()` and `parse_avail_date()`.
- `src/dashboard/_tables.py` → overview-table "Leased" row.
- `src/dashboard/__init__.py` → rent-comps cards "Leased %" (and the
  `is_leaseup` badge for buildings built within ~12 months).
- `src/dashboard/_detail.py` → per-property "vacant_count".
- Availability dates come from `comp_grid_data()` in `src/storage.py`
  (`avail_dates` = each available unit's `available_date`).

## Questions
1. Is the leased/occupancy calc **consistent across all three render sites**
   (overview table, rent-comps cards, detail page) and applied to **every**
   comp in the grid (no property silently skipped or special-cased)?
2. Is the semantics correct and uniform: future-dated availability = occupied;
   only ≤7-day availability = vacant? Do the overview table and the cards agree
   (the cards have an `elif total:` fallback — does it ever diverge)?
3. Edge cases: empty/unparseable `available_date` (is_vacant returns False →
   treated as occupied — right?); properties with 0 available units (→ 100%);
   lease-up buildings whose units all share a far-future delivery date (e.g. 465
   Carpenter → 100% with only the Lease-Up badge to contextualize). Flag any
   that look misleading, but DON'T change anything.
4. Any mismatch between `avail_dates` length and `unit_count` that would make
   Leased and Exposure inconsistent?

Observed current output (sanity reference): IWT 98.2% leased / 15% exposure;
Van Buren 100% / 6.8% (10 future-dated units); 1100 W Grand 44.4% / 55.6%;
465 Carpenter 100% / 45.8% (lease-up).

Keep it concise; cite file:line. Report only — no edits.
