# Codex advisory request — Inspire West Town (IWT) scraper failure

You are acting as a **read-only advisor**. Do not propose to write files; return
analysis only. Claude is the sole writer/committer.

## Context
Repo: rent-comp-tracker. A daily GitHub Actions job scrapes ~13 rental
properties and commits a SQLite snapshot. IWT (property id 2, platform
`rentcafe_optimized`, https://www.iwtchicago.com/floorplans) has been failing
since ~2026-05-20 with this per-property error in the digest:

    FETCH FAILED: setGA4Cookie not found in page — site format may have changed

Relevant code:
- `src/scraper.py` → `fetch_rentcafe_optimized()` (Playwright, headed+xvfb in CI)
  and helpers `_extract_ga4_floorplans`, `_extract_detail_urls`,
  `_extract_units_from_detail`, `_wait_past_cloudflare`.
- `src/parsers/rentcafe_optimized.py` → `parse_all()` and its helpers.

## What I verified against the LIVE site (evidence saved in this folder)
1. **Main page (`iwt_main.sample.html`)**: the data-bearing
   `setGA4Cookie('GT', name, beds, minSqft, maxSqft, minRent, maxRent)` calls
   are GONE. Only the JS *function definition* `setGA4Cookie(tour, fpname, ...)`
   remains. So `_extract_ga4_floorplans()` now returns `[]`, and the hard guard
   `if "setGA4Cookie" not in main_html: raise FetchError(...)` aborts the whole
   fetch before anything else runs. **This is the primary bug.**
2. The main page DOM still cleanly contains 12 floorplan cards (`.fp-container`),
   each with: name (`x02 1 Bed - 1 Bath`), beds/baths/sqft list items,
   `"N Available"` count, `"Starting at $2,490"` (min rent only), an
   `Availability` link to the detail page, and a per-floorplan modal whose
   `.fp-details` carries the full `$2,490 to -$2,695` range + `Available On:`
   date.
3. **Detail pages (`iwt_detail.sample.html`)**: still contain intact
   `applyGAClick('x02 1 Bed - 1 Bath', '1 Bed(s)', '527', '2490.00', '2490.00',
   '702')` anchors with real apartment numbers + MoveInDate in the href. The
   existing `_extract_units_from_detail()` regex matches these correctly.
4. **BUT**: navigating main→detail in the same Playwright page re-triggers a
   Cloudflare "Just a moment..." interstitial. The current detail loop only does
   `time.sleep(2)` — it never waits past Cloudflare on detail pages. In headless
   local Chromium the challenge never clears (40s+), so detail pages yield 0
   units. CI runs headed under xvfb (clears Cloudflare on the main page), but we
   have NO evidence it clears on the 12 secondary detail navigations, because the
   `setGA4Cookie` guard always aborted before the loop ran.

## My proposed fix (already partially drafted)
- (done) Remove the `setGA4Cookie` hard guard; instead fail only if BOTH
  `detail_urls` and `ga4_fps` are empty after extraction.
- (planned) Add a NEW main-page extractor `_extract_floorplan_cards(page)` that
  reads the 12 `.fp-container` cards (name, beds, baths, sqft, availCount,
  min rent from "Starting at $X", and min–max from the modal). Use this as the
  **reliable primary source** so IWT never goes fully dark on one page load.
- (planned) Keep detail-page per-unit extraction as a **best-effort enhancement**:
  replace `time.sleep(2)` with `_wait_past_cloudflare(...)` so it can actually
  clear the challenge when running headed. If detail pages yield units, prefer
  them (real apartment numbers); otherwise fall back to the card-tier data.
- Parser `parse_all()` / `_parse_json_data()` to accept a new `floorplan_cards`
  key alongside `units` and `ga4_floorplans`.

## Questions for you
1. Is my root-cause analysis correct and complete? Any failure mode I missed?
2. Design A (detail pages primary, cards fallback) vs Design B (cards primary,
   detail best-effort). Given reliability vs per-unit granularity, which is the
   better default for a daily unattended job, and why?
3. Review `_extract_detail_urls`, `_extract_ga4_floorplans`,
   `_extract_units_from_detail`, and `parse_all` for OTHER latent bugs (e.g.
   dedup keys, $0/"Contact Us" handling, beds="Studio", balcony name variants,
   md5 floorplan-id collisions, availCount semantics).
4. Any correctness risk in the diffing/storage layer if a property's unit_count
   shape changes from per-unit to per-tier (snapshots are append-only)?

Keep the answer concise and concrete. Cite file:line where relevant.
