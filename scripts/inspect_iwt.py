"""One-off diagnostic: fetch the live IWT floorplans page (headless), capture
the rendered HTML plus any XHR/fetch JSON responses, and report which
data-bearing patterns it now contains.

Run: PYTHONPATH=. python3 scripts/inspect_iwt.py
Writes raw HTML to /tmp/iwt_main.html and JSON bodies to /tmp/iwt_xhr_*.json
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import sync_playwright

from src.config import BROWSER_USER_AGENT

URL = "https://www.iwtchicago.com/floorplans"

PATTERNS = {
    "setGA4Cookie": r"setGA4Cookie\(",
    "ysi.unitsList": r"ysi\.unitsList",
    "ysi.floorplansList": r"ysi\.floorplansList",
    "applyGAClick": r"applyGAClick\(",
    "fpName": r"fpName",
    "__NEXT_DATA__": r"__NEXT_DATA__",
    "ld+json": r"application/ld\+json",
    "$ rent figures": r"\$\s?\d[\d,]{2,}",
}


def main() -> None:
    captured: list[dict] = []
    bodies: list[tuple[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=BROWSER_USER_AGENT,
                                  viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                url = resp.url
                interesting = ("json" in ct or any(k in url.lower() for k in
                               ("api", "floorplan", "availab", "rentcafe", "unit")))
                if interesting:
                    captured.append({"url": url, "status": resp.status, "ct": ct})
                    if "json" in ct:
                        try:
                            bodies.append((url, resp.text()))
                        except Exception:
                            pass
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(URL, wait_until="domcontentloaded", timeout=45000)

        title = ""
        html = ""
        for i in range(20):
            time.sleep(2)
            try:
                title = page.title()
            except Exception:
                break
            print(f"  ({(i+1)*2}s) title: {title!r}")
            if "moment" not in title.lower() and "challenge" not in title.lower():
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                try:
                    html = page.content()
                except Exception as e:
                    print(f"  content() failed: {e}")
                break

        print("\n==== PAGE REPORT ====")
        print(f"final title : {title!r}")
        print(f"html length : {len(html):,} bytes")
        if html:
            with open("/tmp/iwt_main.html", "w") as f:
                f.write(html)
            print("raw saved   : /tmp/iwt_main.html")
            print("\n---- pattern presence ----")
            for label, pat in PATTERNS.items():
                print(f"  {label:20s}: {len(re.findall(pat, html))} hit(s)")

        try:
            links = page.evaluate("""() => Array.from(
                document.querySelectorAll('a[href*=\"/floorplans/\"]')
            ).map(a => a.href)""")
            uniq = sorted(set(links))
            print(f"\n---- {len(uniq)} unique /floorplans/ links ----")
            for u in uniq[:30]:
                print(f"  {u}")
        except Exception as e:
            print(f"  link scan failed: {e}")

        browser.close()

    print(f"\n---- {len(captured)} json/api responses ----")
    seen = set()
    for c in captured:
        key = c["url"].split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{c['status']}] {c['ct'][:25]:25s} {c['url'][:150]}")

    for idx, (url, body) in enumerate(bodies):
        path = f"/tmp/iwt_xhr_{idx}.json"
        with open(path, "w") as f:
            f.write(body)
        print(f"  saved body {path} ({len(body):,} bytes) <- {url[:90]}")


if __name__ == "__main__":
    main()
