"""End-to-end verification of the IWT (rentcafe_optimized) fix.

Mirrors fetch_rentcafe_optimized() but forces headless (the headed browser is
flaky on this Mac; CI uses xvfb-headed). Drives the *real* card extractor and
the real parser, so a green run here proves the pipeline works against the live
site.

Run: PYTHONPATH=. python3 scripts/verify_iwt_fetch.py
"""
from __future__ import annotations

import json
import time

from playwright.sync_api import sync_playwright

from src.config import BROWSER_USER_AGENT
from src.scraper import _extract_floorplan_cards, _extract_ga4_floorplans
from src.parsers.rentcafe_optimized import parse_all

URL = "https://www.iwtchicago.com/floorplans"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent=BROWSER_USER_AGENT, viewport={"width": 1920, "height": 1080}
        ).new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        for _ in range(15):
            time.sleep(2)
            t = page.title()
            if "moment" not in t.lower() and "challenge" not in t.lower():
                break
        try:
            page.wait_for_selector(".fp-container", timeout=10000)
        except Exception as e:
            print(f"  (.fp-container wait: {e})")

        main_html = page.content()
        cards = _extract_floorplan_cards(page)
        ga4 = _extract_ga4_floorplans(main_html)
        browser.close()

    print(f"cards: {len(cards)}  ga4 tiers: {len(ga4)}")
    assert cards or ga4, "guard would fire — nothing found"

    result = json.dumps({"floorplan_cards": cards, "ga4_floorplans": ga4})
    units, floorplans = parse_all(result)
    print(f"\nPARSED: {len(units)} tier-units across {len(floorplans)} floorplans\n")
    for u, f in zip(units, floorplans):
        print(f"  {u['UnitCode']:>12}  {u['FloorplanName'][:30]:30s} "
              f"{u['Beds']}bd/{u['Baths']}ba {u['SqFt']:>4}sf  "
              f"${u['MinRent']}-${u['MaxRent']}  x{f['AvailableCount']}  "
              f"avail {u['AvailableDate'] or '—'}  est={u['IsEstimated']}")
    assert units, "no units parsed — fix incomplete"
    assert all(u["IsEstimated"] for u in units), "tier units must be estimated"
    assert all(u["UnitCode"].startswith("FP-") for u in units), "stable codes"
    print("\nOK: pipeline produced stable, estimated tier data from one page load.")


if __name__ == "__main__":
    main()
