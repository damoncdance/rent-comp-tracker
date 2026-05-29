# Parked Improvements

Items identified from Codex code review (2026-05-10). Implement when relevant.

## Do Soon

**4. Migration runner in CI — DONE (2026-05-29)**
Added `migrations/runner.py` (discovers `NNN_*.py` migrations, applies pending ones,
tracks them in a `schema_migrations` ledger) and wired `python -m migrations.runner`
into `daily.yml` after the DB-init step. Idempotent and safe to run every day.

**5. Arthurs of Old Town health**
Low success rate. The AppFolio parser may need investigation — could be zero vacancies
or a site change. Worth a scraper-recovery pass.

**6. SecureCafe interpolation flagging**
Interpolated rents from SightMap feed into pricing recommendations without being marked
as estimated. Should add an `is_estimated` flag, but needs schema + pricing logic changes.

## Park

**7. Typed data models (dataclasses/Pydantic)**
Every parser, storage, dashboard, and notify module passes dicts. Correct architectural
direction but massive refactor. Not worth it until a major feature addition.

**8. Provenance flags on parsed data**
Couples with typed models (#7). Park together.

**9. Parser replay command**
Nice-to-have for debugging. Raw HTML is already saved; a replay command would be ~30 lines.
Low priority.

**10. Dependency hash pinning / security scan**
We have 4 well-known deps. A `pip-audit` CI step would be the minimal version. Low risk.

**11. Broader test coverage**
Parser tests exist because parsers break most often. Storage/diff/dashboard tests are
lower ROI — those break loudly in practice.

**12. Operational health dashboard page**
The email digest + GitHub annotations already surface failures. Would be a Phase 5 addition.

**13. Property registry in seed file**
The DB via migrations is the source of truth. Fine for a single-operator tool.
