"""Print every analyte's full course: first value, last value, direction, range.

The input for writing plain-English significance grounded in this patient's
actual numbers rather than textbook generalities.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C


def main() -> int:
    d = json.loads(C.LABS_JSON.read_text())
    series = {}
    for o in d["observations"]:
        if o.get("value") is None:
            continue
        series.setdefault(o["analyte"], []).append(o)

    for key in sorted(series, key=lambda k: (C.ANALYTES.get(k, {}).get("group", "zz"), k)):
        rows = sorted(series[key], key=lambda o: o["collected"])
        meta = C.ANALYTES.get(key, {})
        vals = [r["value"] for r in rows]
        ref = rows[-1].get("reference", {})
        lo, hi = ref.get("low"), ref.get("high")
        flags = {r.get("interpretation") for r in rows if r.get("interpretation")}
        crit = any(r.get("critical") for r in rows)

        span = f"{vals[0]:g}" if len(vals) == 1 else f"{vals[0]:g} -> {vals[-1]:g}"
        print(f"{meta.get('group','?'):11} {key:20} n={len(vals):2} {span:22} "
              f"unit={rows[-1].get('unit','')!r:14} ref={lo}-{hi} "
              f"flags={sorted(flags)} {'CRITICAL' if crit else ''}")
        print(f"{'':32} all: {', '.join(f'{v:g}' for v in vals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
