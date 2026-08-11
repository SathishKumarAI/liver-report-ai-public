"""List values where the OCR passes disagree, and montage their crops.

These are the values a human must actually look at. Everything else has three
independent readings that agree.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C


def main() -> int:
    d = json.loads(C.LABS_JSON.read_text())
    rows = []
    for o in d["observations"]:
        readings = {v for v in o["provenance"]["ocr"].values() if v is not None}
        if len(readings) > 1:
            rows.append(o)
    rows.sort(key=lambda o: (o["analyte"], o["page"]))

    print(f"values with disagreeing OCR passes: {len(rows)}")
    tiles = []
    out = C.DATA / "verify"
    out.mkdir(parents=True, exist_ok=True)

    for i, o in enumerate(rows):
        ocr = o["provenance"]["ocr"]
        label = (f"p{o['page']:03d}  {o['analyte']}  chosen={o['value']}  "
                 f"A={ocr.get('A')} B={ocr.get('B')} C={ocr.get('C')}  "
                 f"flag={o.get('printed_flag')}  ref={o['reference']['text'][:20]}")
        print("  " + label)
        crop = o["provenance"].get("crop")
        if not crop:
            continue
        src = C.REPO / crop
        if not src.exists():
            continue
        tile = out / f"_d{i:02d}.png"
        subprocess.run(
            [C.MAGICK, str(src), "-resize", "980x", "-bordercolor", "white", "-border", "3",
             "-background", "#eeeeee", "-splice", "0x30", "-pointsize", "19",
             "-fill", "black", "-annotate", "+8+21", label, str(tile)],
            check=True, capture_output=True)
        tiles.append(str(tile))

    if tiles:
        sheet = out / "disagreements.png"
        subprocess.run([C.MAGICK, *tiles, "-append", str(sheet)],
                       check=True, capture_output=True)
        for t in tiles:
            Path(t).unlink(missing_ok=True)
        print(f"\nmontage: {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
