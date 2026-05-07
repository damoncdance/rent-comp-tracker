---
name: scraper-recovery
description: Use when the daily fetch starts failing — HTTP 403, HTTP 5xx, or the parser can no longer find ysi.unitsList in the HTML. Covers diagnosis (is the site down, blocking us, or restructured?) and the three remediation paths (header rotation, curl_cffi, headless Playwright). Use whenever src/scraper.py or src/parser.py needs investigation due to runtime failures.
---

# Scraper recovery playbook

When `data/cron.log` shows fetch or parse failures, work through these steps
in order. Don't jump to a heavyweight fix until lighter ones are ruled out.

## 1. Diagnose first

```bash
# What does the failure snapshot say?
sqlite3 data/tracker.db \
  "SELECT id, fetched_at, fetch_status, http_status FROM snapshots
   WHERE fetch_status != 'success' ORDER BY id DESC LIMIT 5;"
```

Three failure modes, three different fixes:

| Symptom                                  | Likely cause              | Fix path |
|------------------------------------------|---------------------------|----------|
| `http_status = 403` repeatedly           | Bot detection on UA/headers | §2 |
| `http_status = 200` but `parse:...`      | Site restructured or platform changed | §4 |
| `http_status = 5xx` or network error     | Site is down — wait it out | nothing |
| `http_status = 429`                      | Rate-limited (running too often?) | reduce frequency |

Always confirm the site loads in your real browser before spending time on
client-side fixes. If it's down for everyone, no code change will help.

## 2. Header rotation (try this first for 403)

`src/config.py` has `DEFAULT_HEADERS`. The User-Agent eventually goes stale
as Chrome version numbers advance. Bump it to a current real Chrome:

```python
# src/config.py
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/<CURRENT>.0.0.0 Safari/537.36"
    ),
    ...
}
```

Find the current Chrome major version on
[useragentstring.com](https://useragentstring.com/pages/Chrome/) or just
copy yours from `chrome://version`.

If header bump alone doesn't work, also add cookies the site sets on first
load — open DevTools, copy the request as cURL, extract the cookie header,
and add it to `DEFAULT_HEADERS["Cookie"]`. Cookies eventually expire; this
is a stopgap, not a permanent fix.

## 3. curl_cffi fallback (TLS fingerprinting)

If a real browser still works but `requests` gets 403, the site is doing
TLS fingerprinting (it can tell `requests` apart from a real browser at the
TLS handshake level, before any HTTP). Switch to `curl_cffi`, which mimics
a Chrome TLS fingerprint:

```bash
pip install curl_cffi
```

Modify `src/scraper.py` — replace the `requests.get(...)` call with:

```python
from curl_cffi import requests as cffi_requests
resp = cffi_requests.get(
    PROPERTY_URL, headers=DEFAULT_HEADERS,
    timeout=REQUEST_TIMEOUT_SECONDS, impersonate="chrome120",
)
```

This is a 5-line change and resolves most 403 cases that header rotation can't.

## 4. Playwright headless browser (last resort)

If the site has actually started executing JS to gate the data, or it's hidden
behind a Cloudflare interactive challenge, switch to a real headless browser:

```bash
pip install playwright
playwright install chromium
```

New file `src/scraper_browser.py`:

```python
from playwright.sync_api import sync_playwright
from src.config import PROPERTY_URL, REQUEST_TIMEOUT_SECONDS

def fetch_html_browser() -> tuple[str, int]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        resp = page.goto(PROPERTY_URL, timeout=REQUEST_TIMEOUT_SECONDS * 1000)
        page.wait_for_load_state("networkidle")
        html = page.content()
        status = resp.status if resp else 200
        browser.close()
        return html, status
```

Then in `src/daily_run.py`, swap `from src.scraper import fetch_html` for the
browser version. Everything downstream — parser, storage, dashboard —
keeps working unchanged because the embedded `ysi.unitsList` array is the same
whether the HTML came from `requests` or a real browser.

Cost: Playwright runs are ~10× slower (5–15s per fetch) and add ~300MB to
the install footprint. Worth it only when steps 2–3 don't work.

## 5. Parser broke (parse:... failures)

If `ysi.unitsList` regex stops matching, the site has either:

(a) **Renamed the variable.** Inspect the HTML for similar patterns:
```bash
grep -oE 'ysi\.[a-zA-Z]+List' data/raw/$(date -u +%Y-%m-%d).html | sort -u
```
Update the regex in `src/parser.py`.

(b) **Switched to a different platform** (e.g. moved off RentCafe to Yardi
Voyager, AppFolio, or a custom CMS). Open the page, view source, find the new
data structure, and rewrite `parser.py`. The rest of the codebase doesn't
need to change as long as `parse_units` returns dicts with `UnitCode`, `Beds`,
`Baths`, `SqFt`, `MinRent`, `MaxRent`, `AvailableDate`, `FloorplanId`,
`FloorplanName` keys.

The `data/raw/*.html` archive is your safety net here — you can replay
historical snapshots through a new parser and not lose data.
