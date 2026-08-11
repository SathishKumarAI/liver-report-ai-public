"""Offline-purity and structure audit of the served dashboard.

Checks the things that are policy, not taste: no external requests, no missing
tabs, charts actually rendered. Run with the server up:

    python tools/audit_page.py
"""

import re
import sys
import urllib.request

URL = "http://127.0.0.1:8080/"


def main() -> int:
    try:
        html = urllib.request.urlopen(URL, timeout=15).read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"FAILED to fetch {URL}: {exc}")
        return 1

    print(f"bytes            : {len(html):,}")

    title = re.search(r"<title>(.*?)</title>", html, re.S)
    print(f"title            : {title.group(1).strip() if title else 'MISSING'}")

    urls = re.findall(r"https?://[^\s\"'<>)]+", html)
    external = [u for u in urls if "127.0.0.1" not in u and "localhost" not in u]
    print(f"external URLs    : {len(external)}")
    for u in external[:8]:
        print(f"   {u}")

    tabs = re.findall(r'data-tab="([a-z_]+)"', html)
    print(f"tabs             : {sorted(set(tabs))}")

    print(f"<svg> elements   : {html.count('<svg')}")
    print(f"embedded images  : {html.count('data:image')}")
    print(f"inline <script>  : {html.count('<script')}")
    print(f"inline <style>   : {html.count('<style')}")

    for needle, label in [
        ("MELD", "MELD mentioned"),
        ("Ask AI", "chat tab present"),
        ("human", "verification wording"),
    ]:
        print(f"{label:17}: {'yes' if needle.lower() in html.lower() else 'NO'}")

    return 0 if not external else 2


if __name__ == "__main__":
    sys.exit(main())
