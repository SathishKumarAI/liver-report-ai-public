"""Print the daily score table. Quick eyeball of completeness and trajectory."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C


def main() -> int:
    d = json.loads(C.LABS_JSON.read_text())
    print(f"{'date':12} {'MELD3':>6} {'MELD-Na':>8} {'CTP':>5} {'AARC':>5}   missing")
    for s in d["scores"]:
        m, n, c, a = s["meld3"], s["meld_na"], s["child_pugh"], s["aarc"]
        missing = set(m.get("missing", [])) | set(a.get("missing", []))
        print(f"{s.get('date', s['collected'][:10]):12} "
              f"{str(m['value']):>6} {str(n['value']):>8} "
              f"{str(c['value']):>5} {str(a['value']):>5}   "
              f"{','.join(sorted(missing))[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
