"""Structural privacy checks that need no secret denylist.

`scan_phi.py` is the thorough gate, but it needs the pattern list, and that list
cannot live in a public repository — it contains the strings it exists to
exclude. Forks and first-time contributors therefore run without it.

This file is the part that still works with nothing secret at all. It looks for
the SHAPE of a leak rather than its content:

  - file types and paths that can only be patient material
  - identifier-shaped tokens next to the labels that introduce them
  - a committed dataset that does not declare itself synthetic
  - a built page that would make a network request

None of these can be defeated by choosing a different hospital or a different
patient, which is what makes them worth running everywhere.

    python tools/ci_privacy_check.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
                   ".webp", ".dcm", ".tsv", ".hocr"}
BANNED_PREFIXES = ("data/", "dist/")

# Identifier-shaped tokens are only reported when they sit next to a label that
# introduces one. A bare seven-digit number is a lab value or a line count far
# more often than it is a hospital number; "UHID: 1234567" is not.
LABELLED_ID = re.compile(
    r"(?:uhid|mrn|nhs\s*no|hospital\s*(?:no|number)|patient\s*(?:id|no)|"
    r"ip\s*no|op\s*no|accession|sample\s*no|episode\s*no)"
    r"\s*[:#=]?\s*[A-Za-z]{0,4}[-.]?\d{5,}", re.I)

PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -]?)?(\d{10})(?!\d)")


def _is_degenerate(digits: str) -> bool:
    """True for digit runs that cannot be a phone number.

    The OCR character whitelists in this project are literally "0123456789",
    which matches every phone-shaped pattern ever written. Rejecting ascending,
    descending and single-repeated runs removes that false positive without
    weakening the check for anything that looks like a real number.
    """
    if len(set(digits)) <= 2:
        return True
    ascending = all(int(b) - int(a) == 1 for a, b in zip(digits, digits[1:]))
    descending = all(int(a) - int(b) == 1 for a, b in zip(digits, digits[1:]))
    return ascending or descending
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DOB = re.compile(r"\b(?:d\.?o\.?b|date\s+of\s+birth)\b", re.I)

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
# This file necessarily contains the patterns it searches for.
SELF = Path(__file__).name


def tracked_files() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [f for f in r.stdout.splitlines() if f.strip()]


def main() -> int:
    problems: list[str] = []
    files = tracked_files()

    # ---- 1. file types and paths ----
    for f in files:
        if Path(f).suffix.lower() in BANNED_SUFFIXES:
            problems.append(f"tracked file of a patient-data type: {f}")
        if f.startswith(BANNED_PREFIXES):
            problems.append(f"tracked path that should never be committed: {f}")

    # ---- 2. identifier-shaped content ----
    for f in files:
        p = ROOT / f
        if p.name == SELF or not p.is_file():
            continue
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for rx, what in ((LABELLED_ID, "a labelled patient identifier"),
                         (PHONE, "a phone-number-shaped token"),
                         (EMAIL, "an email address"),
                         (DOB, "a date-of-birth field")):
            for m in rx.finditer(text):
                if rx is PHONE and _is_degenerate(m.group(1)):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                # The match itself is not echoed: printing it into a public CI
                # log would publish the thing being protected.
                problems.append(f"{f}:{line} contains {what}")
                break

    # ---- 3. any committed dataset must declare itself synthetic ----
    for f in files:
        if not f.endswith(".json"):
            continue
        p = ROOT / f
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(blob, dict) and "observations" in blob:
            if not blob.get("synthetic"):
                problems.append(
                    f"{f} is a dataset but is not marked \"synthetic\": true")

    # ---- 4. a built page must not reach the network ----
    dash = ROOT / "dist" / "dashboard.html"
    if dash.exists():
        html = dash.read_text(encoding="utf-8", errors="ignore")
        external = [u for u in re.findall(r"https?://[^\s\"'<>)]+", html)
                    if "127.0.0.1" not in u and "localhost" not in u]
        if external:
            problems.append(f"built dashboard makes {len(external)} external request(s)")

    print(f"tracked files checked: {len(files)}")
    if problems:
        print(f"\nFAIL - {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        print("\nThis tree must not be published. See PRIVACY.md.")
        return 1

    print("\nPASS - no patient-data file types, no labelled identifiers, "
          "no undeclared dataset, no external requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
