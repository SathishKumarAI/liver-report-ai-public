"""Build verification contact sheets: every extracted value beside its own pixels.

Groups crops by analyte so a whole time series is checked at once -- an outlier
in a column of numbers is obvious in a way a single crop never is.

    python tools/verify_sheets.py            # build sheets
    python tools/verify_sheets.py --list     # print what is on each sheet

Sheets land in data/verify/ (gitignored). Reviewing them is the human gate that
data/review.json records.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C

OUT = C.DATA / "verify"
PER_SHEET = 22
CROP_WIDTH = 900


def label_for(o: dict) -> str:
    val = o.get("value")
    flag = o.get("printed_flag") or "-"
    ocr = o.get("provenance", {}).get("ocr", {})
    passes = "/".join(str(ocr.get(k)) for k in ("A", "B", "C"))
    return f"p{o['page']:03d}  {o['analyte']}={val} [{flag}]  ABC={passes}"


def main(list_only: bool = False) -> int:
    dataset = json.loads(C.LABS_JSON.read_text())
    obs = [o for o in dataset["observations"]
           if o.get("value") is not None and o.get("provenance", {}).get("crop")]
    obs.sort(key=lambda o: (o["analyte"], o.get("collected") or ""))

    OUT.mkdir(parents=True, exist_ok=True)
    sheets, current, current_analytes = [], [], set()

    def flush():
        if not current:
            return
        idx = len(sheets) + 1
        sheets.append({"sheet": idx, "items": [label_for(o) for o in current],
                       "analytes": sorted(current_analytes)})
        if list_only:
            current.clear()
            current_analytes.clear()
            return
        tiles = []
        for o in current:
            crop = C.REPO / o["provenance"]["crop"]
            if not crop.exists():
                continue
            tile = OUT / f"_t{idx}_{len(tiles):02d}.png"
            subprocess.run(
                [C.MAGICK, str(crop), "-resize", f"{CROP_WIDTH}x", "-bordercolor", "white",
                 "-border", "3", "-background", "#f2f2f2", "-splice", "0x30",
                 "-pointsize", "20", "-fill", "black", "-annotate", f"+8+21", label_for(o),
                 str(tile)], check=True, capture_output=True)
            tiles.append(str(tile))
        if tiles:
            subprocess.run([C.MAGICK, *tiles, "-append", str(OUT / f"sheet_{idx:02d}.png")],
                           check=True, capture_output=True)
            for t in tiles:
                Path(t).unlink(missing_ok=True)
        current.clear()
        current_analytes.clear()

    last_analyte = None
    for o in obs:
        # Keep an analyte's series on one sheet where possible.
        if len(current) >= PER_SHEET and o["analyte"] != last_analyte:
            flush()
        current.append(o)
        current_analytes.add(o["analyte"])
        last_analyte = o["analyte"]
    flush()

    (OUT / "index.json").write_text(json.dumps(sheets, indent=1))
    print(f"values with crops : {len(obs)}")
    print(f"sheets            : {len(sheets)}")
    for s in sheets:
        print(f"  sheet_{s['sheet']:02d}  {len(s['items']):2d} values  {', '.join(s['analytes'][:6])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--list" in sys.argv))
