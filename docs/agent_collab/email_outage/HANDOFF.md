# Email outage + digest noise — handoff (2026-11-10)

**Status: RESOLVED.** The scheduled run on 2026-11-10 (Actions run 42894297276)
went green end to end: scrape → commit `c53bc5d` → Pages deploy → digest
delivered to the work inbox at 20:24 UTC.

Commits: `d9478b7` (main fix), `41ab18a` (alert + push-retry follow-up).

## Symptom

"Something is wrong with the emails." Daily digests stopped arriving after
2026-11-04.

## Root causes

| # | Problem | Impact | Fix |
|---|---------|--------|-----|
| 1 | `ubuntu-latest` moved to Ubuntu 26.04 around 2026-11-05. Playwright 1.59 refuses to install Chromium there (`Playwright does not support chromium on ubuntu26.04-x64`). | Every run from Nov 5 to Nov 9 died at "Install dependencies". No data, no dashboard, **no email**. | Pinned `runs-on: ubuntu-24.04` in `daily.yml`. |
| 2 | The digest is sent from inside `daily_run`, so a failure in setup, install, tests or migrations sent nothing. The "inbox is a heartbeat" promise only covered failures inside the scrape. | The outage was silent. The same thing happened on 2026-10-26, when the install step timed out at 5 minutes. | Added an `if: failure()` step that emails `Rent Comps — RUN FAILED` with a link to the run, using system `python3` and the standard library only. Raised the install timeout to 10 minutes. |
| 3 | Sites stamp available-now units with *today's* date, so `available_date` rolls forward daily and `changes.py` logged a `date_changed` event every day. | About 75% of digest "changes" were noise: 478 of 624 events over Oct 28–Nov 4. | `changes._both_available_now()` skips the event when the unit was move-in ready in both snapshots. Replaying Oct 28–Nov 4 gives 624 → 150 events, with every rent change, add and removal kept. |
| 4 | The HTML digest showed "FAILED" without saying why. Pricing-section errors were swallowed. | Hard to triage from the inbox. | Failure reason is shown under the property name, and `notify: pricing section omitted — …` is now logged. |

## Problems found while verifying (both fixed in `41ab18a`)

- **The first alert attempt returned HTTP 403 from Resend.** Resend's Cloudflare
  front rejects urllib's default User-Agent, so the alert now sets
  `User-Agent: rent-comp-tracker/1.0` and logs Resend's error body if a send
  fails. *Not yet observed sending successfully, because no run has failed since
  the fix.* To test it, temporarily add `exit 1` to a step on a branch and use
  `workflow_dispatch`.
- **The manual run at 16:26 UTC could not push** (`remote rejected … fatal error
  in commit_refs_rules`) during a GitHub Git-operations incident. There are no
  rulesets or branch protection on `main`. That run's data was lost; the 20:20
  scheduled run replaced it. The commit step now retries `git push` 4 times with
  backoff and runs `pull --rebase` between attempts.

## Things that were not the problem

- **Delivery and Resend config.** Every digest through Nov 4 reached
  `NOTIFY_TO`, the owner's **work (M365) mailbox**, not Gmail. Searching Gmail
  finds nothing, which is expected. The sender is still `onboarding@resend.dev`
  (Resend free tier, no verified domain).
- **Notify code.** Sends succeeded on every run that reached them, with retries
  and attachments working.

## Open items (not addressed)

1. **The Jax** (securecafe): `pageData not found after Cloudflare challenge`,
   73% success over the last 30 days. Needs a scraper-recovery pass
   (`.claude/skills/scraper-recovery/`).
2. **Seven 10 West** (nestio): `No listings returned from Nestio API` on
   2026-11-10 (96% success over 30 days). This may just be zero vacancy; watch it.
3. **Runner pin is a time bomb in reverse.** `ubuntu-24.04` will eventually be
   retired. When bumping Playwright, check Ubuntu 26.04 support and then unpin.
   `actions/checkout@v4` and `setup-python@v5` also warn about Node 20
   deprecation.
4. **The cron fires 3–10 hours late.** It is scheduled for 13:00 UTC but has
   started between 16:00 and 23:00 UTC. That is GitHub scheduling load. If the
   digest needs to land by morning, trigger it from an external scheduler or the
   m5 server instead.
5. **Minor email polish:**
   - Multi-property subjects say "0 changes", never the "no changes" format in
     CLAUDE.md.
   - The pricing cards use `display:flex`, which Gmail and Outlook render poorly.
   - `_resend_attachment_for_snapshot` and the `workbook_attached` path in
     `src/notify/` are dead code.
   - `src/notify/` has no tests.
6. **Expect one inflated digest after any outage.** After a gap, the first diff
   compares against the last *committed* snapshot. The Nov 10 digest showed 80
   changes because it diffed against Nov 4. It should settle to the real daily
   churn, mostly Spoke and Westerly rent moves.

## How to verify quickly

```bash
gh run list --workflow daily.yml -L 5            # green?
gh run view <id> --log | grep -E 'notify:|Done\.|Diff vs'
python -m pytest -q                              # 90 tests, incl. tests/test_changes.py
```
