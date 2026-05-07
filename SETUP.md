# Setup

This walks you from a fresh GitHub repo to a fully automated, cloud-hosted
rent comp tracker with daily snapshots, email digests, and a public dashboard.

**Total setup time: ~25 minutes.** After this, the system runs itself.

Your dashboard will end up at:
**`https://damoncdance.github.io/rent-comp-tracker/`**

## What you'll do

1. Get a Resend API key (5 min)
2. Push the project to GitHub (5 min)
3. Add the three secrets to your repo (3 min)
4. Enable GitHub Pages (1 min)
5. Run the workflow once manually to verify (5 min)
6. Confirm the email arrived and the dashboard loads (2 min)

## 1. Get the Resend API key

If you've already done this, skip to step 2.

1. Sign up at [resend.com](https://resend.com) (free).
2. Verify your signup email when Resend sends the confirmation.
3. Go to **API Keys** in the left sidebar → **Create API Key**.
4. Name: "Rent Comp Tracker". Permission: **Sending access**. Domain: leave as
   "All domains".
5. Click **Add**. Resend shows the key once — it starts with `re_` followed by
   a long string. **Copy it now.** You can't see it again, only revoke and
   regenerate.

Paste it into a temporary text file or password manager. You'll need it in
step 3.

## 2. Push the project to GitHub

You should already have an empty repo at
[github.com/damoncdance/rent-comp-tracker](https://github.com/damoncdance/rent-comp-tracker).
If not, create one (public, no README, no .gitignore, no license).

Open a terminal in the unzipped project folder
(`/Users/damondance/Documents/Code-Projects/rent-comp-tracker`) and run:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/damoncdance/rent-comp-tracker.git
git push -u origin main
```

If git asks for credentials, use a **Personal Access Token**, not your
password. (GitHub deprecated password auth years ago.) If you don't have a
token: GitHub → Settings → Developer settings → Personal access tokens →
Tokens (classic) → Generate new token → check `repo` scope → copy the token
and paste when prompted.

After the push, refresh the repo page in your browser — you should see all
the files: `CLAUDE.md`, `src/`, `schema.sql`, `.github/workflows/daily.yml`,
etc.

## 3. Add the three secrets

These are credentials the GitHub Actions workflow will use. They're encrypted
at rest by GitHub and never visible in logs, even to you.

In your repo on GitHub:

1. Click **Settings** (in the repo's top nav, not your account settings).
2. In the left sidebar: **Secrets and variables → Actions**.
3. Click **New repository secret** and add each of these one at a time:

| Name | Value |
|---|---|
| `RESEND_API_KEY` | The `re_...` key from step 1 |
| `NOTIFY_FROM` | `Rent Comps <onboarding@resend.dev>` |
| `NOTIFY_TO` | The email address you signed up to Resend with |

The `NOTIFY_FROM` value above works without any domain verification. The
`NOTIFY_TO` must be the same email Resend has on file for you — that's a
Resend free-tier restriction that lifts once you verify a domain (see
"Optional: verify a domain" at the bottom).

After adding all three, the secrets list should show three entries with
"Updated now" timestamps. Values are hidden — that's correct.

## 4. Enable GitHub Pages

1. Still in repo Settings, scroll down the left sidebar to **Pages**.
2. Under **Build and deployment → Source**, select **GitHub Actions**.
   (Not "Deploy from a branch" — we're using the workflow.)
3. That's it. There's nothing else to configure here.

## 5. Run the workflow once manually

The first run shouldn't wait for tomorrow's 6:30 AM trigger — let's prove
everything works now.

1. In your repo, click the **Actions** tab.
2. In the left sidebar, click **"Daily snapshot"**.
3. Click the **"Run workflow"** dropdown on the right → keep the default
   branch (main) → click the green **"Run workflow"** button.
4. Refresh the page. A new run should appear within a few seconds, marked
   yellow (in progress).
5. Click into the run. Click the `snapshot` job. Watch the steps execute.
   The full run takes about 60–90 seconds.

You're looking for green checkmarks on every step. If any step fails, click
into it for details — see the troubleshooting section below.

## 6. Verify everything wired up

Three things should be true after the first successful run:

**(a) Email arrived.** Check the inbox you used as `NOTIFY_TO`. Subject
should be `Rent Comps — Aberdeen Crossing: 76 units, no changes` (or similar).
If it's not in your inbox, check spam. If still not there: Actions tab → run
log → look for any line starting with `notify:`. It tells you whether the
send succeeded, failed, or was skipped.

**(b) Dashboard is live.** Open
[`https://damoncdance.github.io/rent-comp-tracker/`](https://damoncdance.github.io/rent-comp-tracker/)
in a browser. The first time, give it 1–2 minutes after the workflow finishes
— Pages can be slow on the first deploy. You should see the property name,
unit counts, and a unit table.

**(c) Repo has new commits.** Refresh the repo's main page. There should be
a recent commit by `github-actions[bot]` with a message like
`Daily snapshot: 2026-05-08 12:30 UTC`. That commit contains the updated
`data/tracker.db` and `dashboard/index.html`.

If all three are true: **you're done.** The workflow is now scheduled and
will run automatically every day at 12:30 UTC (6:30 AM Central winter / 7:30
AM Central summer). You don't need to touch anything.

## Optional: develop / test locally

You don't need to run anything locally for the cloud version to work, but if
you want to iterate on the code:

```bash
cd rent-comp-tracker
pip install -r requirements.txt

# For local runs: copy the env template and fill in your Resend key
cp .env.example .env
# Then edit .env and set NOTIFY_ENABLED=true if you want test emails

# Initialize a local DB (separate from the cloud one)
sqlite3 data/tracker.db < schema.sql

# Run a snapshot
python -m src.daily_run --verbose

# Test just the email layer without re-fetching
python -m src.notify --test
```

Caveat: local runs and cloud runs both write to `data/tracker.db`. The cloud
keeps the authoritative copy, so don't commit local test data — work on a
branch, or `rm data/tracker.db` before pushing if you've been experimenting.

## Optional: verify a domain in Resend

The free Resend setup limits you to: send from `onboarding@resend.dev`, send
to the email you signed up with. That's enough for a personal tracker.

If you want to send to teammates or send from a custom address (e.g.
`rentcomps@yourdomain.com`):

1. In Resend → Domains → Add Domain.
2. Add the DNS records Resend gives you (SPF, DKIM, DMARC) at your domain
   registrar. Takes 10–30 minutes for DNS to propagate.
3. Once verified, change the `NOTIFY_FROM` secret in GitHub to use your
   domain (e.g. `Rent Comps <rentcomps@yourdomain.com>`).
4. Add additional recipients to `NOTIFY_TO` (comma-separated).

You don't need to redeploy — the next scheduled run picks up the new secrets.

## Changing the daily run time

The schedule lives in `.github/workflows/daily.yml`:

```yaml
on:
  schedule:
    - cron: '30 12 * * *'   # 12:30 UTC daily
```

GitHub Actions cron is UTC. To run at 9:00 AM Central year-round:
- Winter (CST = UTC-6): 9:00 AM Central = 15:00 UTC → `0 15 * * *`
- Summer (CDT = UTC-5): 9:00 AM Central = 14:00 UTC → `0 14 * * *`

Pick the one that matters most to you (most people pick winter time, which
runs an hour earlier in summer). Edit the cron string, commit, and push:

```bash
git add .github/workflows/daily.yml
git commit -m "Adjust schedule"
git push
```

The change takes effect on the next scheduled run.

## Troubleshooting

**Workflow fails at "Run daily snapshot" with HTTP 403.** The site is
blocking the GitHub Actions IP range. See
`.claude/skills/scraper-recovery/SKILL.md` for remediation. This is rare for
RentCafe sites but can happen.

**Workflow fails at "Commit updated data and dashboard".** Usually a
permissions issue. Check repo Settings → Actions → General → Workflow
permissions → make sure "Read and write permissions" is selected.

**Pages deploy fails with 404 or HttpError.** Make sure you set Source =
"GitHub Actions" in Settings → Pages (step 4). The default
"Deploy from a branch" won't work with this workflow.

**Email doesn't arrive but workflow shows green.** Click the run → snapshot
job → "Run daily snapshot" step → search the log for `notify:`. Common
causes: secret name typo (Resend rejects the API key as invalid), `NOTIFY_TO`
isn't your Resend signup email (Resend rejects with "you can only send to
verified emails").

**Email goes to spam.** The first email Resend sends from `onboarding@resend.dev`
to a Gmail address often lands in spam. Mark it as "Not spam" and future
sends should land in the inbox. Verifying a domain (above) eliminates this
entirely.

## Where things live

- **Code:** the GitHub repo
- **Data history:** `data/tracker.db` in the repo, updated by the daily Action
- **Dashboard:** [`https://damoncdance.github.io/rent-comp-tracker/`](https://damoncdance.github.io/rent-comp-tracker/)
- **Logs:** repo Actions tab → click any run
- **Secrets:** repo Settings → Secrets and variables → Actions
- **Email digests:** the inbox you set as `NOTIFY_TO`
