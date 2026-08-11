"""Final acceptance check on the built dashboard.

Asserts the things that are policy or contract, not taste: no network, every tab
present, the clinical content actually rendered, and the verified coefficient
present with the wrong one absent.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C

MUST_CONTAIN = [
    ("MELD 3.0", "MELD 3.0 named"),
    ("1.83", "verified albumin x creatinine coefficient"),
    ("Child-Pugh", "Child-Pugh"),
    ("AARC", "AARC"),
    ("Maddrey", "Maddrey"),
    ("not medical advice", "scope disclaimer"),
    ("blood-gas lactate", "AARC lactate specimen labelled"),
]
# Regexes, not bare substrings. A plain search for "1.72" fired on an unrelated
# system-burden figure that happened to read 1.729x. The check has to match the
# formula TERM -- 1.72 multiplied by a (3.5 - albumin) bracket -- not the digits.
MUST_NOT_CONTAIN = [
    (r"1\.72\s*[*x×·]?\s*\(?\s*3\.5", "the WRONG albumin x creatinine coefficient"),
    (r"cellsfcumm", "mangled OCR unit"),
    (r"mmolft", "mangled OCR unit"),
]

TABS = ["summary", "days", "trends", "patterns", "doctor",
        "formulas", "validation", "glossary", "ask"]


def visible_text(html: str) -> str:
    """The markup, with the embedded dataset JSON removed.

    The provenance block deliberately keeps the raw OCR unit ("cellsfcumm") as
    part of the audit trail, so a naive search of the whole file finds mangled
    strings that are never shown to anyone. Only rendered markup is checked.
    """
    return re.sub(r"<script[^>]*type=\"application/json\"[^>]*>.*?</script>", "",
                  html, flags=re.S)


def main() -> int:
    html = C.DASHBOARD.read_text(encoding="utf-8")
    shown = visible_text(html)
    failures = []

    urls = [u for u in re.findall(r"https?://[^\s\"'<>)]+", html)
            if "127.0.0.1" not in u and "localhost" not in u]
    print(f"external URLs        : {len(urls)}")
    if urls:
        failures.append(f"external URLs present: {urls[:5]}")

    found = set(re.findall(r'data-tab="([a-z_]+)"', html))
    missing = [t for t in TABS if t not in found]
    print(f"tabs                 : {len(found)} present")
    if missing:
        failures.append(f"missing tabs: {missing}")

    for needle, label in MUST_CONTAIN:
        ok = needle.lower() in shown.lower()
        print(f"  {label:42} {'yes' if ok else 'MISSING'}")
        if not ok:
            failures.append(f"missing: {label}")

    for needle, label in MUST_NOT_CONTAIN:
        bad = re.search(needle, shown) is not None
        print(f"  absent: {label:34} {'LEAKED' if bad else 'ok'}")
        if bad:
            failures.append(f"present but must not be: {label}")

    print(f"size                 : {len(html):,} bytes")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nall dashboard checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
