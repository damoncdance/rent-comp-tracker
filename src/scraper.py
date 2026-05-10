"""Fetch a property's floorplans page. Returns (html, http_status) or raises FetchError.

For most platforms, a simple requests.get() with browser-like headers suffices.
SecureCafe sites sit behind Cloudflare bot protection and require a real browser
(Playwright) to solve the JS challenge.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.config import (
    DEFAULT_HEADERS, REQUEST_TIMEOUT_SECONDS,
    MAX_RETRIES, RETRY_BACKOFF_SECONDS, RAW_DIR,
)


class FetchError(Exception):
    """Raised when fetching fails after all retries."""


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
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FetchError(
            "playwright is not installed — required for SecureCafe sites. "
            "Run: pip install playwright && python -m playwright install chromium"
        )

    if verbose:
        print(f"  Playwright fetch: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for Cloudflare challenge to resolve and page to render
            page_data = None
            for i in range(20):
                time.sleep(2)
                title = page.title()
                if verbose:
                    print(f"    waiting ({(i+1)*2}s) — title: {title}")

                # Once past Cloudflare, extract pageData
                if "moment" not in title.lower():
                    try:
                        page_data = page.evaluate("JSON.stringify(pageData)")
                        break
                    except Exception:
                        # pageData might not be defined yet
                        if i > 5:
                            break
                        continue

            html = page.content()
            browser.close()

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
    """Fetch unit-level data from a RentCafe 'optimized' site via Playwright.

    These sites don't have ysi.unitsList. Instead we:
    1. Visit the main /floorplans page (past Cloudflare)
    2. Extract GA4 floorplan-tier data from setGA4Cookie calls
    3. Find "Availability" links to floorplan detail pages
    4. Visit each detail page and extract real unit data from applyGAClick()

    Returns (json_string, 200) where json_string contains:
    - "units": list of unit dicts with real apartment numbers
    - "ga4_floorplans": floorplan-tier data as fallback
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FetchError(
            "playwright is not installed — required for Cloudflare-protected sites. "
            "Run: pip install playwright && python -m playwright install chromium"
        )

    if verbose:
        print(f"  Playwright fetch (rentcafe_optimized): {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for Cloudflare challenge to resolve
            for i in range(20):
                time.sleep(2)
                title = page.title()
                if verbose:
                    print(f"    waiting ({(i+1)*2}s) — title: {title}")
                if "moment" not in title.lower() and "challenge" not in title.lower():
                    time.sleep(3)
                    break

            main_html = page.content()

            if not main_html or len(main_html) < 500:
                raise FetchError("Page content too short — Cloudflare may not have resolved")

            if "setGA4Cookie" not in main_html:
                raise FetchError("setGA4Cookie not found in page — site format may have changed")

            # Extract GA4 floorplan-tier data from main page
            ga4_fps = _extract_ga4_floorplans(main_html)
            if verbose:
                print(f"    Found {len(ga4_fps)} floorplan tiers from GA4 data")

            # Find floorplan detail page URLs (only those with "Availability" links)
            detail_urls = _extract_detail_urls(page)
            if verbose:
                print(f"    Found {len(detail_urls)} floorplan detail pages to visit")

            # Visit each detail page and extract unit-level data
            all_units = []
            for detail_url in detail_urls:
                try:
                    page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(2)
                    units = _extract_units_from_detail(page)
                    all_units.extend(units)
                    if verbose:
                        print(f"    {detail_url.split('/floorplans/')[-1]}: {len(units)} units")
                except Exception as e:
                    if verbose:
                        print(f"    Failed to fetch detail page {detail_url}: {e}")

            browser.close()

        result = json.dumps({
            "units": all_units,
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


def _extract_detail_urls(page) -> list[str]:
    """Find unique floorplan detail page URLs from "Availability" links."""
    urls = page.evaluate("""() => {
        const seen = new Set();
        const urls = [];
        document.querySelectorAll('a[href*="/floorplans/"]').forEach(a => {
            const href = a.href;
            if (href && !href.endsWith('/floorplans') && !href.endsWith('/floorplans/')) {
                if (!seen.has(href)) {
                    seen.add(href);
                    urls.push(href);
                }
            }
        });
        return urls;
    }""")
    return urls


def _extract_units_from_detail(page) -> list[dict]:
    """Extract unit data from applyGAClick() calls on a detail page."""
    return page.evaluate("""() => {
        const units = [];
        document.querySelectorAll('a[onclick*="applyGAClick"]').forEach(a => {
            const onclick = a.getAttribute('onclick') || '';
            const href = a.getAttribute('href') || '';
            const match = onclick.match(
                /applyGAClick\\('([^']+)',\\s*'([^']*)',\\s*'([^']*)',\\s*'([^']*)',\\s*'([^']*)',\\s*'([^']*)'/
            );
            if (match) {
                const dateMatch = href.match(/MoveInDate=([^&]+)/);
                units.push({
                    fpName: match[1],
                    beds: match[2],
                    sqft: match[3],
                    minRent: match[4],
                    maxRent: match[5],
                    unitNumber: match[6],
                    moveInDate: dateMatch ? decodeURIComponent(dateMatch[1]) : ''
                });
            }
        });
        return units;
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
