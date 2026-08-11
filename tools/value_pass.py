"""Pass C, done properly: re-read every value from its own bounding box.

Why this exists as a repair rather than part of extract.py's pass loop:
pass C was configured as a whole-page OCR with tessedit_char_whitelist set to
digits. That destroys every analyte name on the page, so the geometric parser
matched no rows and pass C returned None for all 395 values -- the ensemble was
silently running on two passes, not three, and the contact sheets showed it
(ABC=20.2/20.2/None on every row).

The fix is to apply the whitelist where it was always meant to go: the value box
alone, which contains only a number. There the whitelist does its job -- O/0,
l/1, S/5 and B/8 confusion become impossible by construction rather than
unlikely, which is the whole reason for having a third pass.

    python tools/value_pass.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C, ocr, parse

WHITELIST = "0123456789.-"


def read_value(image: Path, bbox, work: Path) -> float | None:
    x, y, w, h = bbox
    pad_x, pad_y = 10, 6
    box = (max(0, x - pad_x), max(0, y - pad_y), w + 2 * pad_x, h + 2 * pad_y)
    for psm in ("7", "8", "6"):
        try:
            raw = ocr.ocr_region(image, box, work, psm=psm,
                                 whitelist=WHITELIST, scale_str="300%")
        except RuntimeError:
            continue
        value, _flag, _raw = parse.parse_value(raw)
        if value is not None:
            return value
    return None


def main() -> int:
    path = C.DATA / "raw_observations.json"
    payload = json.loads(path.read_text())
    work = C.OCR_DIR / "work"
    work.mkdir(parents=True, exist_ok=True)

    done = agree = disagree = blank = 0
    for i, o in enumerate(payload["observations"], 1):
        if not o.get("bbox"):
            continue
        image = C.PAGES / f"pg-{o['page']:03d}.jpg"
        got = read_value(image, o["bbox"], work)
        o.setdefault("ocr", {})["C"] = got
        done += 1
        if got is None:
            blank += 1
        elif o.get("value") is not None and abs(got - o["value"]) < 1e-9:
            agree += 1
        else:
            disagree += 1
        if i % 100 == 0:
            print(f"  ...{i}", flush=True)

    path.write_text(json.dumps(payload, indent=1))
    print(f"values re-read : {done}")
    print(f"  agree        : {agree}")
    print(f"  disagree     : {disagree}")
    print(f"  unreadable   : {blank}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
