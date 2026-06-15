Read-only audit complete. No edits made.

**Findings**

No current logic bug found. The intended semantics are implemented uniformly where real availability dates are present:

- `is_vacant()` parses the date and returns `False` for blank/unparseable values, so those units are treated as occupied: `src/dashboard/_helpers.py:28-33`, `src/dashboard/_helpers.py:36-53`.
- Vacancy is only counted when `(available_date - today).days <= 7`, so far-future availability remains leased/occupied: `src/dashboard/_helpers.py:33`.
- Overview table computes `leased = (total - vacant) / total`: `src/dashboard/_tables.py:57-67`.
- Rent-comp cards use the same helper/formula when `avail_dates` exists: `src/dashboard/__init__.py:510-514`.
- Detail pages compute `vacant_count` from the same helper and derive `leased_pct` the same way: `src/dashboard/_detail.py:53-56`.

**Consistency Across Comps**

The overview and cards both iterate every property in `grid`: `src/dashboard/_tables.py:60`, `src/dashboard/__init__.py:500`. `grid` comes from `comp_grid_data()`, which selects all active properties without special-casing: `src/storage.py:219-226`.

Detail pages are generated for all active properties too: `src/dashboard/__init__.py:57-60`, using the same active-property source: `src/config.py:27-35`.

**Card Fallback**

The card-only fallback can theoretically diverge:

- Cards fall back to exposure-style occupancy when `avail_dates` is empty/falsy: `src/dashboard/__init__.py:512-518`.
- Overview does not use that fallback; with an empty list it calculates 100% leased: `src/dashboard/_tables.py:63-67`.

In the current storage path, this should not diverge for successful snapshots because `avail_dates` is populated from the same `units` rows that define availability count: `src/storage.py:269-274`, and snapshots store `unit_count = len(units)`: `src/storage.py:57-63`. It would only diverge if `avail_dates` were missing/empty while `unit_count > 0`, which does not appear to be a normal `comp_grid_data()` state.

**Edge Cases**

- Blank/unparseable `available_date` is treated as occupied. That matches the stated rule: `src/dashboard/_helpers.py:31-33`, `src/dashboard/_helpers.py:42-53`.
- Properties with zero available units render as 100% leased in overview/cards/detail when `total > 0`.
- Lease-up buildings with far-future delivery dates can show 100% leased while still having high exposure. That is semantically consistent under the broker-defined rule, but potentially visually misleading; the only contextual cue is the `Lease-Up` badge: `src/dashboard/__init__.py:503-505`, `src/dashboard/__init__.py:550`.

**Mismatch Check**

Current DB check found `snapshots.unit_count == COUNT(units)` for every active property, so Leased and Exposure are not currently inconsistent from row-count mismatch. Examples matching the sanity reference are explained by the logic: Van Buren’s blank/future availability dates count occupied, and 465 Carpenter’s far-future lease-up availability counts occupied while exposure remains high.
