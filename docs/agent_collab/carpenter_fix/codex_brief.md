# Codex advisory request — correct 455 → 465 Carpenter

Read-only advisor. Analysis only; Claude writes/commits.

## Situation
`migrations/004_add_455_carpenter.py` registers a new comp-set property, but the
name/slug/address are wrong. It should be **465 Carpenter**
(https://www.465carpenter.com/, 465 N Carpenter St), not 455. The migration's
`url` is already `465carpenter.com`; only slug/name/address say 455.

Current 004 inserts (INSERT OR IGNORE on slug):
- slug `455-carpenter`, name "455 Carpenter", address "455 N Carpenter St,
  Chicago, IL 60642", url https://www.465carpenter.com/, platform "rentcafe"
  (placeholder), unit_count_total 72, is_subject 0, active **0**, year_built
  2026, stories 5, management_company "Range Group".

## Deployment state (important)
- 004 was committed AND pushed to origin/main today, but the daily workflow has
  NOT run since. Origin's live DB has applied **zero** migrations (no
  `schema_migrations` table). So 004 has never executed in production.
- It HAS been applied to my local dev DB and a throwaway /tmp test DB only.
- The runner applies any migration not in the `schema_migrations` ledger, in
  filename order; migrations are written idempotent.

## Live-site finding
465carpenter.com is a pure Wix marketing site. The `/floorplans` page has no
prices, no availability, and links to NO leasing platform (no
RentCafe/SecureCafe/AppFolio/Sightmap/Entrata). There is nothing scrapable, so
the property should stay `active = 0` until a parseable source exists. (The
daily run loops only active properties, so it will be skipped.)

## Questions
1. Correct in place (edit migration 004's slug/name/address to 465) vs add a new
   corrective migration 005 that UPDATEs the row? Given 004 has never run in
   production and only touched throwaway dev DBs, which is the right call, and
   what's the risk of each? Consider the slug being the INSERT-OR-IGNORE key.
2. If you'd edit 004: any reason the old `455-carpenter` slug could linger
   anywhere that matters?
3. Anything else to fix while here (platform placeholder "rentcafe" on an
   unscrapable site — does that risk an accidental fetch if someone flips
   active=1 later)? Keep it minimal.

Concise, concrete, cite file:line.
