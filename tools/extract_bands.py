"""One-off: read every grey sample band in the document and report coverage.

Kept as a tool rather than a test because it walks all 112 pages and takes
minutes. Its output, data/ocr/bands.json, is the sample timeline the parser
joins observations onto.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C, ocr, render


def main() -> int:
    work = C.OCR_DIR / "work"
    work.mkdir(parents=True, exist_ok=True)

    pages = sorted(C.PAGES.glob("pg-*.jpg"))
    records, missing = [], []

    for i, page in enumerate(pages, 1):
        geo = render.analyse_page(page, i)
        for band in geo.bands:
            if band.kind != "sample":
                continue
            got = ocr.read_band(page, band, geo.width, work)
            got.pop("raw", None)
            got.pop("votes", None)
            got["page"] = i
            records.append(got)
            if not got["collected"]:
                missing.append(i)

    (C.OCR_DIR / "bands.json").write_text(json.dumps(records, indent=1))

    dated = [r for r in records if r["collected"]]
    days = sorted({r["collected"][:10] for r in dated})
    ids = [r for r in records if r["sample_id"]]

    print(f"sample bands found      : {len(records)}")
    print(f"with collection datetime: {len(dated)}")
    print(f"with sample id          : {len(ids)}")
    print(f"pages missing a datetime: {missing}")
    print(f"distinct collection days: {days}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
