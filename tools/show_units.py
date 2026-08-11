"""Show the unit chosen for each analyte and any printed/expected mismatches."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C


def main() -> int:
    d = json.loads(C.LABS_JSON.read_text())
    seen = {}
    for o in d["observations"]:
        seen.setdefault(o["analyte"], o)

    for key in ("wbc", "platelets", "anc", "alc", "hemoglobin", "lactate", "creatinine"):
        o = seen.get(key)
        if o:
            print(f"{key:12} {str(o['value']):>9}  shown={o['unit']!r:16} "
                  f"printed={o['provenance'].get('unit_as_printed')!r}")

    mismatches = [o for o in d["observations"] if o["provenance"].get("unit_mismatch")]
    print(f"\nunit mismatches flagged: {len(mismatches)}")
    grouped = {}
    for o in mismatches:
        m = o["provenance"]["unit_mismatch"]
        grouped.setdefault((o["analyte"], m["printed"], m["expected"]), 0)
        grouped[(o["analyte"], m["printed"], m["expected"])] += 1
    for (analyte, printed, expected), n in sorted(grouped.items()):
        print(f"  {analyte:16} printed={printed!r:18} dictionary says={expected!r:14} x{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
