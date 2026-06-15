"""Fetch a property's floorplans page. Returns (html, http_status) or raises FetchError.

For most platforms, a simple requests.get() with browser-like headers suffices.
SecureCafe sites sit behind Cloudflare bot protection and require a real browser
(Playwright) to solve the JS challenge.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.config import (
    BROWSER_USER_AGENT, DEFAULT_HEADERS, REQUEST_TIMEOUT_SECONDS,
    MAX_RETRIES, RETRY_BACKOFF_SECONDS, RAW_DIR,
)


class FetchError(Exception):
    """Raised when fetching fails after all retries."""


# --- Shared Playwright plumbing --------------------------------------------
# Both SecureCafe and RentCafe-optimized sites sit behind Cloudflare and need
# a real (headed) browser. The launch/context setup and the Cloudflare wait
# loop are identical, so they live here once.

_PW_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--window-size=1920,1080",
]
_PW_VIEWPORT = {"width": 1920, "height": 1080}


@contextmanager
def _browser_page(verbose: bool = False):
    """Yield a Chromium page configured to slip past Cloudflare.

    Handles the missing-Playwright case, browser launch/teardown, and the
    shared context options (viewport + real-browser UA). Callers drive
    navigation and extraction.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FetchError(
            "playwright is not installed — required for Cloudflare-protected sites. "
            "Run: pip install playwright && python -m playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=_PW_LAUNCH_ARGS)
        try:
            context = browser.new_context(
                viewport=_PW_VIEWPORT,
                user_agent=BROWSER_USER_AGENT,
            )
            yield context.new_page()
        finally:
            browser.close()


def _wait_past_cloudflare(
    page,
    *,
    block_titles: tuple[str, ...] = ("moment",),
    settle_seconds: float = 0.0,
    max_waits: int = 20,
    step_seconds: float = 2.0,
    verbose: bool = False,
) -> str:
    """Poll the page title until the Cloudflare interstitial clears.

    `block_titles` are lowercase substrings that indicate we're still on the
    challenge page. Once none match, optionally wait `settle_seconds` for the
    real page to render, then return the final title.
    """
    for i in range(max_waits):
        time.sleep(step_seconds)
        title = page.title()
        if verbose:
            print(f"    waiting ({(i + 1) * step_seconds:.0f}s) — title: {title}")
        low = title.lower()
        if not any(b in low for b in block_titles):
            if settle_seconds:
                time.sleep(settle_seconds)
            return title
    return page.title()


def fetch_html(
    url: str,
    slug: str = "unknown",
    save_raw: bool = True,
    verbose: bool = False,
) -> tuple[str, int]:
    """Fetch the page with retries. Returns (html_text, http_status_code).

    save_raw: when True, write the raw HTML to data/raw/<slug>/YYYY-MM-DD.html
              so we can re-parse historical snapshots if the parser changes.
    """
    last_error: Exception | None = None
    last_status: int | None = None

    # For JSON API endpoints, drop brotli from Accept-Encoding (Python 3.9
    # requests can't decompress it) and request JSON explicitly.
    headers = dict(DEFAULT_HEADERS)
    if "wp-json" in url or "api" in url:
        headers["Accept"] = "application/json"
        headers["Accept-Encoding"] = "gzip, deflate"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if verbose:
                print(f"  fetch attempt {attempt}/{MAX_RETRIES}: {url}")
            resp = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            last_status = resp.status_code

            if resp.status_code == 200:
                html = resp.text
                if save_raw:
                    _write_raw(html, slug)
                return html, 200

            # Non-200: sleep and retry, unless it's a hard 4xx that won't change.
            if 400 <= resp.status_code < 500 and resp.status_code not in (408, 429):
                raise FetchError(
                    f"HTTP {resp.status_code} (won't retry; check headers/UA)"
                )
            last_error = FetchError(f"HTTP {resp.status_code}")
        except requests.RequestException as e:
            last_error = e
            if verbose:
                print(f"  network error: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise FetchError(
        f"All {MAX_RETRIES} attempts failed. "
        f"Last status={last_status}, last_error={last_error}"
    )


def fetch_securecafe(
    url: str,
    slug: str = "unknown",
    save_raw: bool = True,
    verbose: bool = False,
) -> tuple[str, int]:
    """Fetch a SecureCafe page via Playwright, solving Cloudflare challenge.

    Returns (pageData_json, 200) where pageData_json is the JSON-serialized
    pageData object extracted from the page via JS evaluation.
    """
    if verbose:
        print(f"  Playwright fetch: {url}")

    try:
        with _browser_page(verbose=verbose) as page:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for Cloudflare to clear, then extract pageData. pageData may
            # not be defined the instant the title clears, so keep polling.
            page_data = None
            for i in range(20):
                time.sleep(2)
                title = page.title()
                if verbose:
                    print(f"    waiting ({(i+1)*2}s) — title: {title}")

                if "moment" not in title.lower():
                    try:
                        page_data = page.evaluate("JSON.stringify(pageData)")
                        break
                    except Exception:
                        # pageData might not be defined yet
                        if i > 5:
                            break
                        continue

        if page_data is None:
            raise FetchError("pageData not found after Cloudflare challenge")

        # Validate it's real JSON
        parsed = json.loads(page_data)
        if "floorplans" not in parsed:
            raise FetchError("pageData missing 'floorplans' key")

        if save_raw:
            _write_raw(page_data, slug)

        return page_data, 200

    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"Playwright fetch failed: {e}")


def fetch_rentcafe_optimized(
    url: str,
    slug: str = "unknown",
    save_raw: bool = True,
    verbose: bool = False,
) -> tuple[str, int]:
    """Fetch floorplan-tier data from a RentCafe 'optimized' floorplans page.

    Around mid-2026 these sites moved their pricing into the rendered DOM —
    one card per floorplan carrying min/max rent, sqft, and an available
    count — and dropped the old setGA4Cookie('GT', ...) data calls (only the
    JS function definition remains). Real per-apartment data still lives on
    Cloudflare-gated /floorplans/<plan> detail pages, but those re-trigger the
    challenge and scraping ~12 of them per run is slow and unreliable, so we
    read the floorplan cards from a single resolved page load instead. The
    parser flags these tier-level rows as estimated.

    Returns (json_string, 200) where json_string contains:
    - "floorplan_cards": list of card dicts (primary source)
    - "ga4_floorplans": GA4 tier data if the site still emits it (fallback)
    """
    if verbose:
        print(f"  Playwright fetch (rentcafe_optimized): {url}")

    try:
        with _browser_page(verbose=verbose) as page:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for Cloudflare to clear (both interstitial titles), then
            # give the SPA a moment to render the floorplan list.
            _wait_past_cloudflare(
                page,
                block_titles=("moment", "challenge"),
                settle_seconds=3.0,
                verbose=verbose,
            )

            main_html = page.content()

            if not main_html or len(main_html) < 500:
                raise FetchError("Page content too short — Cloudflare may not have resolved")

            # Wait for the floorplan cards to render (it's a SPA). Don't hard
            # fail if the selector never appears — we still try the GA4
            # fallback below for legacy/variant layouts.
            try:
                page.wait_for_selector(".fp-container", timeout=10000)
            except Exception:
                if verbose:
                    print("    .fp-container not found in 10s — trying GA4 fallback")

            cards = _extract_floorplan_cards(page)

            # GA4 floorplan-tier data (setGA4Cookie('GT', ...) calls) was dropped
            # from these pages, but keep extracting it as a fallback for sites
            # that still emit it.
            ga4_fps = _extract_ga4_floorplans(main_html)
            if verbose:
                print(f"    Found {len(cards)} floorplan cards, {len(ga4_fps)} GA4 tiers")

            # If neither cards nor GA4 data are present, the page really did
            # change shape (or Cloudflare never resolved) — surface it.
            if not cards and not ga4_fps:
                raise FetchError(
                    "No floorplan cards or GA4 data found — "
                    "site format may have changed"
                )

        result = json.dumps({
            "floorplan_cards": cards,
            "ga4_floorplans": ga4_fps,
        })

        if save_raw:
            _write_raw(result, slug)

        return result, 200

    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"Playwright fetch failed: {e}")


def _extract_ga4_floorplans(html: str) -> list[dict]:
    """Extract floorplan-tier data from setGA4Cookie('GT', ...) calls."""
    pattern = re.compile(
        r"setGA4Cookie\(\s*'GT'\s*,"
        r"\s*'([^']+)'\s*,"
        r"\s*'(\d+)'\s*,"
        r"\s*'(\d+)'\s*,"
        r"\s*'(\d+)'\s*,"
        r"\s*'(\d+)'\s*,"
        r"\s*'(\d+)'\s*\)",
    )
    seen = set()
    results = []
    for name, beds, min_sqft, max_sqft, min_rent, max_rent in pattern.findall(html):
        if name not in seen:
            seen.add(name)
            results.append({
                "name": name, "beds": beds,
                "minSqft": min_sqft, "maxSqft": max_sqft,
                "minRent": min_rent, "maxRent": max_rent,
            })
    return results


def _extract_floorplan_cards(page) -> list[dict]:
    """Extract tier-level data from the rendered floorplan cards.

    Each `.fp-container` card carries the RentCafe floorplan id/name and the
    bed/bath/sqft + "N Available" count; the matching `#modal-content-<id>`
    holds the min–max rent range and the soonest move-in date. Returns one
    dict per floorplan (deduped by id).
    """
    return page.evaluate(r"""() => {
        // floorplan id -> canonical name, from whichever element carries both
        const nameById = {};
        document.querySelectorAll('[data-floorplan-id][data-floorplan-name]').forEach(e => {
            nameById[e.getAttribute('data-floorplan-id')] = e.getAttribute('data-floorplan-name');
        });

        const cards = [];
        const seen = new Set();
        document.querySelectorAll('.fp-container').forEach(card => {
            const idEl = card.querySelector('[data-floorplan-id]');
            if (!idEl) return;
            const fpId = idEl.getAttribute('data-floorplan-id');
            if (!fpId || seen.has(fpId)) return;
            seen.add(fpId);

            const text = (card.innerText || '').replace(/\s+/g, ' ');
            const heading = card.querySelector('h2, h3, h4');
            const name = nameById[fpId] || (heading ? heading.innerText.trim() : '');
            const avail = (text.match(/(\d+)\s+Available/i) || [])[1] || '';
            const sqft  = (text.match(/([\d,]+)\s*Sq\.?\s*Ft/i) || [])[1] || '';

            // Rent range + move-in date live in the per-floorplan modal.
            let minRent = '', maxRent = '', availDate = '';
            const modal = document.getElementById('modal-content-' + fpId);
            if (modal) {
                const rentEl = modal.querySelector('.text-2x');
                if (rentEl) {
                    const nums = (rentEl.innerText.match(/\$[\d,]+/g) || [])
                                     .map(s => s.replace(/[^\d]/g, ''));
                    if (nums.length) { minRent = nums[0]; maxRent = nums[nums.length - 1]; }
                }
                const d = (modal.innerText || '').match(/Available On:\s*([\d/]+)/i);
                if (d) availDate = d[1];
            }
            // Fall back to the card's "Starting at $X" (min rent only).
            if (!minRent) {
                const sm = text.match(/Starting at\s*\$([\d,]+)/i);
                if (sm) { minRent = sm[1].replace(/,/g, ''); maxRent = minRent; }
            }

            cards.push({ fpId, name, sqft, availCount: avail, minRent, maxRent, availDate });
        });
        return cards;
    }""")


def _write_raw(html: str, slug: str) -> Path:
    """Save HTML under data/raw/<slug>/YYYY-MM-DD.html."""
    if not re.match(r'^[a-z0-9][a-z0-9-]*$', slug):
        slug = re.sub(r'[^a-z0-9-]', '', slug.lower()) or "unknown"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prop_dir = RAW_DIR / slug
    prop_dir.mkdir(parents=True, exist_ok=True)
    path = prop_dir / f"{today}.html"
    path.write_text(html, encoding="utf-8")
    return path
