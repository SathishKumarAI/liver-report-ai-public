"""Verify the printed Doctor flowsheet is not silently clipping columns.

The flowsheet lives in an overflow-x:auto container. Browsers do not paginate
horizontally, so without print CSS the paper copy loses the right-hand columns
with no indication anything is missing -- the worst kind of defect in a document
a clinician reads on a ward round.

    python tools/check_print.py <doctor.pdf>
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PDFTOTEXT = r"C:\Users\PRANAS\AppData\Local\Programs\MiKTeX\miktex\bin\x64\pdftotext.exe"

# Values from the LAST day of the stay. If the printout stops early these are
# the ones that vanish.
LATE_VALUES = ["23.2", "2.56", "3.36", "140"]
EARLY_VALUES = ["20.2", "3.89"]


def main(pdf: str) -> int:
    text = subprocess.run([PDFTOTEXT, "-layout", pdf, "-"],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout

    failures = []
    print("early-stay values (should be present):")
    for v in EARLY_VALUES:
        ok = v in text
        print(f"  {v:8} {'yes' if ok else 'MISSING'}")
        if not ok:
            failures.append(f"early value {v} missing")

    print("late-stay values (these vanish when columns are clipped):")
    for v in LATE_VALUES:
        ok = v in text
        print(f"  {v:8} {'yes' if ok else 'MISSING'}")
        if not ok:
            failures.append(f"late value {v} missing from printout")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nprinted flowsheet spans the whole admission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
