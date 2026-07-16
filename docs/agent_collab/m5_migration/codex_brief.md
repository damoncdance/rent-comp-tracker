You are a read-only migration-strategy reviewer. Verdict-style review requested.

CONTEXT
This repo (rent-comp-tracker) is being prepared to migrate a WORKING COPY to an
always-on Mac server ("m5", user `damon`, home `/Users/damon`, target
`~/code-projects/rent-comp-tracker`). Source is a mobile Mac (`damondance`,
`~/Documents/Code-Projects/rent-comp-tracker`).

KEY DECISION (locked with owner): Production STAYS on GitHub Actions (the daily
cron in .github/workflows/daily.yml that scrapes, commits data/tracker.db +
dashboard/ back to origin/main, emails via Resend, deploys GitHub Pages). Only
the dev working copy moves to m5, for remote access + a faster dev box. So GitHub
is canonical, NOT m5 (this inverts the usual "server becomes canonical" rule).

The full plan is in MIGRATION_AUDIT_2026-07-16.md at the repo root. Read it.

REVIEW TASK
Verify every factual claim against the live repo state (git, .gitignore,
requirements.txt, src/config.py, .github/workflows/daily.yml, migrations/,
scripts/ask_codex.sh, presence/absence of .env and .venv). Specifically check:

1. Is the "git clone, not rsync" recommendation actually safe? Is there ANY
   precious file outside git that a clone would drop (any gitignored-but-needed
   file, any local .env, any untracked payload other than screenshots/)?
2. Is the canonical-writer / pull-before-edit discipline (§7, §10-A/B) correct
   and sufficient? Any divergence/data-loss footgun I missed with the tracked
   binary data/tracker.db being committed daily by Actions?
3. Are the §9 commands correct and non-destructive? Flag any that could clobber
   the canonical repo, push a bad local snapshot, or force-push over the bot.
   Check the sed target, the remnant sweep, the target-exists guard.
4. Is the venv/runtime section right? (no local .venv to freeze; requirements.txt
   exact-pinned == manifest is the lock; python 3.11 prod vs 3.12 dev skew;
   `playwright install chromium`; dropping xvfb-run on macOS.)
5. Anything in the plan that is WRONG, unsafe, or missing for a dev-clone move.

Output: a short verdict (PASS / PASS-WITH-FIXES / BLOCK) then a numbered list of
findings with severity (BLOCK/SHOULD-FIX/NIT), each tied to a file:line where
possible. Be terse. Do not write any files.
