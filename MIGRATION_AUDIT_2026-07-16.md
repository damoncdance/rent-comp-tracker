# Migration Audit — rent-comp-tracker → damon-m5-server (2026-07-16)

> **Codex-reviewed 2026-07-16 (read-only sandbox, codex-cli 0.142.5): verdict
> PASS-WITH-FIXES — all SHOULD-FIX + NIT items folded in below (log in §12).**
> Review brief + output: `docs/agent_collab/m5_migration/codex_brief.md` /
> `codex_review.md`. Clone-is-safe and the venv/runtime claims were verified good.
> **STATUS: EXECUTED 2026-07-16 — dev clone live on m5, all gates green.** §9 was run:
> pre-flight committed+pushed (`21e7be6`); m5 cloned to `~/code-projects/rent-comp-tracker`
> (SSH remote, clean tree); venv built on py3.12.13 from the pinned manifest (`pip check` OK);
> Chromium installed; migrations all skip (DB current); **80/80 pytest passed**; imports
> resolve with `PROJECT_ROOT=/Users/damon/code-projects/rent-comp-tracker`. Production
> unchanged (still GitHub Actions).
> ⚠️ **Connectivity note:** the `m5` ssh alias (`damon-m5-server.local`, mDNS) does NOT resolve
> off the home LAN — use **`m5-ts`** (Tailscale, `~/.ssh/config`) which works anywhere both
> boxes run Tailscale. All §9 server steps above were run via `m5-ts`.
> This was the plan for review/execution, following the same pattern as the prior migrations.
> Reusable procedure: `~/Documents/chicago-land-sourcing/docs/MIGRATION_PLAYBOOK.md`.
> Prior worked examples: chicago `MIGRATION_AUDIT_2026-06-30.md`, consilia
> `MIGRATION_AUDIT_2026-07-03.md`, devise-brokerage-os `MIGRATION_AUDIT_2026-07-05.md`,
> fitness-app `MIGRATION_AUDIT_2026-07-05.md`.
> **Next step:** codex read-only review of this audit (`scripts/ask_codex.sh`), then
> address blockers, then execute §9.

---

## 0. Machine facts

- **Source:** mobile Mac, user `damondance`, home `/Users/damondance`. This repo:
  `~/Documents/Code-Projects/rent-comp-tracker` (under `Code-Projects/`).
- **Destination:** always-on `damon-m5-server`, ssh alias `m5`, user `damon`, home
  `/Users/damon`. Target: `~/code-projects/rent-comp-tracker` (lowercase parent).
- **Already on m5 (Phase A, from prior migrations):** `~/code-projects/` parent, Homebrew
  `python@3.12` at `/opt/homebrew/bin/python3.12`, git identity, global ignore
  (`~/.config/git/ignore` → `**/.claude/settings.local.json`), passwordless SSH, GitHub SSH
  key. `~/.config/devise/secrets.env` exists — **irrelevant to this repo** (rent-comp-tracker
  does not read it; do not touch).

## 1. The headline divergence — production is ALREADY always-on (GitHub Actions), so this is a *dev-clone* move, not a service relocation

Every prior migration took a repo that ran on a laptop and moved it to m5 **to become
always-on** — ending with *"the server becomes canonical"* (playbook **G12**). **This repo
inverts that.** rent-comp-tracker's production is a **GitHub Actions cron**
(`.github/workflows/daily.yml`, 13:00 UTC daily): it scrapes every property, commits the
updated `data/tracker.db` + `dashboard/` back to `origin/main`, emails the Resend digest, and
deploys the dashboard to GitHub Pages. It is *already* a serverless, always-on system — the
very model `CLAUDE.md` praises.

**Decision (locked 2026-07-16 with the owner):**
- **Production stays on GitHub Actions.** No reason to move the cron; Actions gives free
  always-on execution + the daily commit-back + Pages hosting for nothing.
- **Only the working copy moves to m5** — for remote access, consolidation next to the
  siblings, and a more powerful box to develop / run manual snapshots on.

**Two consequences that flip the usual playbook:**

1. **GitHub is canonical here — m5 is NOT (inverts G12).** GitHub Actions commits to
   `origin/main` *every day*. The m5 clone is a **downstream working copy**: it must
   `git pull` before any edit, or it diverges from the bot's daily snapshot commits. Do **not**
   treat m5 as the source of truth. The mobile Mac copy becomes redundant the same way — both
   are just clones of a repo whose canonical writer is the Actions bot. (See §7, §10-A.)

2. **A `git clone` is the correct migration method — NOT rsync.** Every sibling needed
   `rsync` because precious state lived *outside* git (consilia's `state.db`, brokerage's 1.3 GB
   cache, fitness's wireframe PDF, all `.env` files). **This repo has none of that** (§5, §6):
   there is **no local `.env`** (secrets live in Actions), and every gitignored dir is
   regenerable. So `git clone git@github.com:damoncdance/rent-comp-tracker.git` on m5 yields a
   clean, correctly-wired checkout with the right SSH remote by construction — no rsync, no
   path-copy hazards, no "did the gitignored payload ride?" gate. **This is the simplest
   migration of the set.**

## 2. What's moving

Repo is **28 MB on disk**; **21 MB of that is `.git`** (it tracks `tracker.db`, a 2.3 MB binary
committed daily, so history is large). A fresh clone is the whole payload.

| Item | Size | In git? | How it travels |
|---|---|---|---|
| repo incl. `.git`, `src/`, `dashboard/`, `data/tracker.db`, `migrations/`, docs | 28 MB | **yes** | **`git clone` from GitHub** (already fully pushed, 0 unpushed) |
| `data/tracker.db` (SQLite, source-of-truth) | 2.3 MB | **yes (tracked!)** | rides the clone — it's *in git*, committed daily by Actions |
| `dashboard/` (generated HTML) | 656 KB | **yes (tracked!)** | rides the clone |
| `screenshots/` (local scratch, 2.8 MB) | 2.8 MB | **no — untracked, NOT gitignored** | **do NOT carry**; regenerable via the screenshot tooling. See §6 hygiene gate — add to `.gitignore` so an `m5` `git add -A` can't commit it. |
| `data/raw/`, `data/exports/`, `data/cron.log` | — | no (gitignored) | **leave behind** — regenerable scrape scratch |
| `artifacts/*` | — | no (gitignored) | **leave behind** — regenerable audit scratch |
| `.env` | — | — | **does not exist locally** — nothing to carry (§5) |
| `.claude/settings.local.json` | tiny | no (global-ignored) | **not needed for dev**; if you want the WebFetch allowlist, copy it out-of-band (no secrets in it, §5) |

## 3. Path couplings — nearly clean

Runtime code is **fully portable**: `src/config.py:9` anchors everything on
`PROJECT_ROOT = Path(__file__).resolve().parent.parent` (playbook **G7** ✓) — `DATA_DIR`,
`DASHBOARD_DIR`, and the `.env` loader all derive from it. `scripts/ask_codex.sh` anchors on
`BASH_SOURCE` (portable). No absolute paths in any `src/`, `scripts/`, `migrations/`, or the
workflow.

Tracked absolute-path references (all **cosmetic docs**, none affect runtime):

```
SETUP.md:43                          /Users/damondance/Documents/Code-Projects/rent-comp-tracker
docs/agent_collab/**/codex_review.md  historical Codex review logs quoting old paths (×many)
```

Because we **clone** (not sed a copied tree), the only worthwhile localization is a one-line
fix to `SETUP.md`; the `docs/agent_collab/*.md` review logs are frozen historical artifacts —
leave them (they quote paths as they were at review time, like this audit does). No `sed` army.

## 4. Runtime / venv

- **Production interpreter: Python 3.11** (`daily.yml:42`, `actions/setup-python`). The m5
  clone is for **development**, where Phase-A **`/opt/homebrew/bin/python3.12`** is the natural
  choice. ⚠️ **Prod/dev Python skew (3.11 vs 3.12):** minor here — nothing in the dep set is
  version-sensitive — but be aware a local run on 3.12 is not a byte-perfect mirror of the
  3.11 Actions run. If you want exact parity, `brew install python@3.12`… no: `python@3.11` and
  build the venv on it. **Recommended:** develop on 3.12 (wheels all exist, §below); rely on the
  Actions run as the authoritative 3.11 gate.
- **The manifest IS the lock.** `requirements.txt` is **exactly pinned** (`==`):
  `requests==2.32.5`, `openpyxl==3.1.5`, `playwright==1.59.0`, `pytest==8.3.5`. This is precisely
  what Actions installs. So the playbook's *"reproduce the working venv, not the manifest"* rule
  (and the `pip freeze`/wheel-test dance) is **N/A** — there is **no local `.venv` to freeze**
  (this repo has only ever run in Actions), and the pinned manifest already is the reproduction
  source. All four pins have cp312/arm64 wheels (requests, openpyxl, pytest are pure-ish;
  playwright 1.59.0 ships arm64 macOS wheels).
- **Playwright browser:** after `pip install`, run **`python -m playwright install chromium`**
  on m5 (downloads the Chromium build). ⚠️ **No `xvfb` on macOS:** the Actions workflow wraps
  the run in `xvfb-run` for a virtual display (Linux headed mode to beat Cloudflare). On m5
  (macOS) there is **no xvfb and none is needed** — Playwright headed mode uses the native
  display, or run headless. Just call `python -m src.daily_run --verbose` directly (no
  `xvfb-run` prefix). **Do not copy the `xvfb-run` line from `daily.yml`.**

## 5. Secrets & config

- **No secrets on the source machine at all.** There is **no local `.env`** (verified: absent).
  Production secrets (`RESEND_API_KEY`, `NOTIFY_FROM`, `NOTIFY_TO`) live **only in GitHub Actions
  repo Secrets** and are injected at workflow runtime. **Nothing secret needs to migrate to m5.**
- **No tracked secrets** — `git ls-files | grep -Ei '\.env$|\.key$|secret|credential'` is empty.
  A `git clone` cannot leak keys.
- **`.env.example`** (tracked, template only) documents the dev knobs. `NOTIFY_ENABLED=false` by
  default — so a local m5 run **sends no email** unless you opt in.
- **Optional (only if you want to test the email digest from m5):** create a repo-local `.env`
  on m5 with a Resend key + `NOTIFY_ENABLED=true`. It's gitignored (`.gitignore` → `.env`). Not
  required for scraping/dashboard/dev work. Consider it a separate, later step — most dev runs
  should leave notify off to avoid spurious digests.
- **`.claude/settings.local.json`** (WebFetch domain allowlist, **no secrets** — verified) is
  covered by the m5 **global** ignore (Phase A). It won't ride a `git clone` (it's gitignored);
  copy it out-of-band only if you want the allowlist locally.

## 6. Git state & hygiene gate

- **Remote EXISTS** (unlike consilia/brokerage/fitness — this matches the *chicago* worked
  example): `origin = https://github.com/damoncdance/rent-comp-tracker.git`. `main` tracks
  `origin/main`, **0 unpushed** (`git rev-list --count @{u}..HEAD` == 0). Clean tip to clone.
- **Working tree:** untracked items are **`screenshots/` (2.8 MB, NOT gitignored)**, this
  audit file, and `docs/agent_collab/m5_migration/` (the Codex brief/review) — plus a stray
  `data/.DS_Store` / `.github/.DS_Store` (DS_Store is gitignored). The audit + review artifacts
  get **committed in §9 pre-flight** (they belong in the canonical repo, like the sibling audits
  and the existing `docs/agent_collab/*` review logs). ⚠️ **`screenshots/` is
  a footgun:** it is untracked *and* not ignored, so a careless `git add -A` on **either** box
  would commit 2.8 MB of local PNGs. **Recommended pre-flight fix:** add `screenshots/` to
  `.gitignore` and commit that (rides to m5 via the clone). Do this on the mobile Mac first so
  it's already in the canonical repo.
- **No coupled repos, no worktrees, no stale branches** — single `main`, one worktree. Nothing
  to prune (contrast consilia's `cos/*` / fitness's `task/*`).
- **Remote protocol:** the clone command uses SSH (`git@github.com:…`) so m5 pushes over its
  Phase-A GitHub key. (The mobile copy uses **HTTPS** — fine to leave; it's becoming redundant.)

## 7. Coupled repos & canonical-writer discipline

- **No coupled/sibling repo** (no `devise-webhook` analog, no cross-repo path defaults). Playbook
  **G10** N/A. Fully self-contained.
- **⚠️ Canonical-writer discipline (the one real operational hazard, §1.1 / §10-A).** GitHub
  Actions is the daily committer. Both the mobile Mac and the new m5 clone are *downstream*.
  Rules going forward:
  - **Always `git pull` before editing** on m5 (and on mobile) — else your local `main` is
    behind the bot's latest `Daily snapshot:` commit and you'll create a divergence / merge on
    push.
  - When you push a code change from m5 and Actions has committed since, you'll need a
    `git pull --rebase` first. Expected and benign — just don't force-push over the bot.
  - **Don't edit both clones in parallel.** Pick m5 as your dev box (per the decision); let the
    mobile copy go stale or delete it after cutover (§ Decommission).

## 8. Divergences from the playbook (rent-comp-tracker-specific)

1. **Production is not moving** — this is a dev-clone relocation, so the playbook's go-live tail
   (launchd/cron/service-links, G11) is **entirely N/A**. No daemon, no boot-survival unit.
2. **`git clone`, not rsync** (§1.2) — nothing precious lives outside git, so the clone is the
   clean, correct method. First migration in the set that skips rsync altogether.
3. **GitHub is canonical, not m5** (§7) — inverts **G12**. The single behavioral rule that
   matters post-migration is *pull-before-edit*.
4. **The tracked binary `data/tracker.db`** rides *inside* git (committed daily by Actions) —
   the opposite of consilia's gitignored `state.db`. No special carry step; `git clone` gets the
   canonical DB.
5. **No `.env`, no secrets to move** (§5) — the leak-gate / secret-carry steps that dominated
   every prior audit collapse to "there's nothing to carry."
6. **`requirements.txt` is the lock** (exact `==` pins) and **there is no local `.venv`** — the
   `pip freeze` + wheel-test ritual (playbook §7 / G5–G6) is N/A; install the pinned manifest.
7. **macOS has no `xvfb`** (§4) — drop the `xvfb-run` wrapper for local runs; it's a
   Linux-Actions-only shim.
8. **Remote already exists** (§6) — no `gh repo create` decision (unlike consilia/brokerage/
   fitness); just clone via SSH.

---

## 9. Executable sequence

> BSD `sed`/tools (macOS both ends). **Nothing below has been run.** The whole thing is short
> because production stays put and the move is a clean clone.

```bash
# ── PRE-FLIGHT A: tidy the canonical repo from the mobile Mac (all commits land HERE) ─────
#   Do EVERY tracked-file change on the canonical repo and push, so the m5 clone lands CLEAN
#   with nothing to edit post-clone (Codex #1). No sed on the server copy.
cd ~/Documents/Code-Projects/rent-comp-tracker
git pull --ff-only                                   # get the bot's latest daily snapshot first
printf 'screenshots/\n' >> .gitignore                # stop the untracked 2.8 MB footgun (§6)
# localize the one cosmetic doc path in the canonical repo (points at the m5 dev box going fwd):
sed -i '' 's#/Users/damondance/Documents/Code-Projects/rent-comp-tracker#/Users/damon/code-projects/rent-comp-tracker#g' SETUP.md
git add .gitignore SETUP.md MIGRATION_AUDIT_2026-07-16.md docs/agent_collab/m5_migration/
git commit -m "Prep m5 dev-clone migration: ignore screenshots/, localize SETUP path, audit + codex review"
git push
git rev-list --count @{u}..HEAD                      # expect 0 (tip pushed → clean to clone)

# ── 1. Server prep: verify Phase A + HARD target-exists guard (exit nonzero, Codex #5) ────
ssh m5 'test -d ~/code-projects \
        && /opt/homebrew/bin/python3.12 --version \
        && git config --global --get core.excludesfile \
        && ssh -o BatchMode=yes -T git@github.com 2>&1 | head -1'   # expect "Hi damoncdance!"
ssh m5 'if [ -e ~/code-projects/rent-comp-tracker ]; then echo "STOP: target exists"; exit 1; fi; echo OK-to-clone'

# ── 2. CLONE (not rsync) into ~/code-projects — wires up the SSH remote by construction ───
#   `git clone` also refuses to overwrite a non-empty dir, so this is doubly safe.
ssh m5 'cd ~/code-projects && git clone git@github.com:damoncdance/rent-comp-tracker.git'

# ── 3. On server: sanity-check the checkout (no edits needed — SETUP.md already localized) ─
ssh m5
cd ~/code-projects/rent-comp-tracker
git remote -v                                        # origin = git@github.com:… (SSH) ✓
git status --short                                   # expect CLEAN (nothing to localize post-clone)
# remnant sweep over RUNTIME surfaces only (docs/agent_collab logs are frozen — excluded):
grep -rn --exclude-dir=.git --exclude-dir=docs \
  -e '/Users/damondance' -e '~/Documents' -e 'Documents/Code-Projects' \
  src scripts migrations CLAUDE.md README.md .github   # expect none

# ── 4. Dev venv from the pinned manifest (no freeze/wheel-test needed — §4) ───────────────
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m playwright install chromium       # browser build (no --with-deps on macOS)

# ── 5. Apply any pending DB migrations against the cloned (canonical) tracker.db ──────────
#     Idempotent; tracked in schema_migrations. The cloned DB is already current, so this is
#     normally a no-op — run it to confirm the runner works on m5.
.venv/bin/python -m migrations.runner

# ── 6. BEHAVIORAL PARITY GATE — prove the toolchain runs on m5 ────────────────────────────
.venv/bin/python -m pytest tests/ -q                  # same suite Actions runs (daily.yml:52)
#   optional: a real (read-only-ish) snapshot run WITHOUT email + WITHOUT xvfb (§4):
#   NOTIFY_ENABLED stays false → no digest sent. This scrapes + writes a snapshot locally.
NOTIFY_ENABLED=false .venv/bin/python -m src.daily_run --verbose
#   ⚠️ a local run mutates BOTH tracked artifacts — data/tracker.db AND dashboard/ — (plus the
#   gitignored data/exports/, which is harmless). GitHub is canonical and Actions commits the
#   authoritative DB+dashboard daily, so NEVER commit/push a manually-generated local snapshot.
#   Reset BOTH tracked paths after the smoke run to stay in sync (Codex #2):
git restore -- data/tracker.db dashboard/            # discard local snapshot; back to origin's tip

# ── 7. Done. Ongoing discipline (§7): pull-before-edit; never force-push over the bot ──────
#   Production is UNCHANGED — GitHub Actions still owns the daily cron, DB commit, and Pages.
#   m5 is now your dev box. `git pull --rebase` before pushing any code change.
```

## 10. Residual risk

- **A — Divergence from the daily bot (top risk, §7).** If you edit on m5 without
  `git pull` first, your push conflicts with the Actions `Daily snapshot:` commit. Mitigation:
  pull-before-edit; `git pull --rebase` before any push. Never force-push.
- **B — Accidentally committing a local snapshot.** A local `src.daily_run` writes **both**
  tracked `data/tracker.db` **and** `dashboard/`; committing either would fight the canonical
  Actions output. Mitigation: `git restore -- data/tracker.db dashboard/` after any local smoke
  run (§9 step 6). Treat local runs as read-only-for-git.
- **B2 — Bot ↔ human push race.** The workflow checks out once, then `git push`es `data/
  dashboard/` at the end **without a pull/rebase** (`daily.yml:118`). If a human pushes to
  `main` while the ~cron run is in flight, the bot's push is rejected and that day's snapshot
  commit is lost (the run itself doesn't retry the push). Mitigation: **don't push to `main`
  during the daily-run window** (~13:00 UTC); if you must and the bot push rejected, just
  re-run the workflow from the Actions tab. (Hardening the workflow to pull-rebase-before-push
  is a separate, optional improvement — out of scope for the dev-clone move.)
- **C — `screenshots/` committed by accident** (untracked + not ignored, 2.8 MB). Mitigation:
  the §9 pre-flight `.gitignore` add closes this on both boxes.
- **D — Prod/dev Python skew (3.11 vs 3.12, §4).** Low risk (deps are version-insensitive), but
  a green local 3.12 run is not a guarantee for the 3.11 Actions run. Mitigation: the daily
  Actions run remains the authoritative gate; don't treat local green as production-green.
- **E — Playwright/Cloudflare behaves differently on m5.** macOS native display + residential IP
  vs Linux-xvfb + GitHub datacenter IP. This is usually *better* locally (residential IPs are
  less blocked), but SecureCafe/Cloudflare behavior can differ. Only matters if you rely on local
  scrape output; production is unaffected (still Actions).
- **F — Stale mobile copy.** After cutover the mobile Mac clone lags `origin` until it fetches.
  Don't edit both. Decommission per below once m5 is your confirmed dev box.

## 11. Decommission (mobile Mac copy — optional, after m5 is confirmed)

- `git -C ~/Documents/Code-Projects/rent-comp-tracker fetch` then
  `git rev-list --count @{u}..HEAD` == 0 (nothing unpushed).
- Nothing gitignored is precious (no `.env`, `screenshots/` regenerable) — safe to delete the
  source **copy** once verified. (Retiring this copy ≠ wiping the mobile box — see playbook
  Decommission note.)

---

## 12. Codex review log (2026-07-16, read-only sandbox — verdict PASS-WITH-FIXES)

Codex verified claims against live repo state (git, `.gitignore`, `requirements.txt`,
`src/config.py`, `daily.yml`, `migrations/`, `.claude/settings.local.json`, and confirmed the
absence of `.env` and `.venv`). **Verified-good (no change):** the clone-is-safe recommendation
(no local `.env`, no `.venv`, `data/tracker.db` + `dashboard/` are tracked, ignored dirs are
non-canonical) and the entire venv/runtime section (exact pins, 3.11 prod vs 3.12 dev, drop
`xvfb-run` on macOS). All findings dispositioned:

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | SHOULD-FIX | Post-clone `sed` on `SETUP.md` left m5 dirty, weakening pull-before-edit | **Fixed** — localization moved to PRE-FLIGHT A on the canonical repo; clone lands clean (§9 step 1/3) |
| 2 | SHOULD-FIX | Smoke-run cleanup only reset `tracker.db`; `daily_run` also writes tracked `dashboard/` | **Fixed** — `git restore -- data/tracker.db dashboard/` (§9 step 6, §10-B) |
| 3 | SHOULD-FIX | Bot↔human push race: workflow pushes without pull/rebase → a human push can drop the day's snapshot | **Fixed (documented)** — new residual risk §10-B2 + operational note; workflow hardening flagged as optional/out-of-scope |
| 4 | SHOULD-FIX | "clean except screenshots" understated: audit + `docs/agent_collab/m5_migration/` also untracked | **Fixed** — §6 reworded; both committed in PRE-FLIGHT A |
| 5 | NIT | Target-exists guard only printed STOP (relied on `git clone` to fail) | **Fixed** — hard `exit 1` guard (§9 step 1) |
| 6 | NIT | Venv/runtime claims all check out | **No change needed** — confirmed good |
```
