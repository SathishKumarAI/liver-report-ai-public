"""Print one page's parsed rows, column by column. For diagnosing extraction gaps.

Usage:  python tools/debug_page.py 57
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C, ocr, parse, render


def main(page_no: int, ocr_pass: str = "A") -> int:
    work = C.OCR_DIR / "work"
    image = sorted(C.PAGES.glob("pg-*.jpg"))[page_no - 1]
    geo = render.analyse_page(image, page_no)
    words = ocr.ocr_words(image, ocr_pass, work)

    rows = parse.to_rows(parse.group_lines(words), geo.width)
    print(f"page {page_no}  rows={len(rows)}  bands={[b.kind for b in geo.bands]}")
    for i, row in enumerate(rows):
        t = row.text("test")[:36]
        r = row.text("result")[:20]
        u = row.text("unit")[:12]
        f = row.text("reference")[:18]
        print(f"{i:3} T={t!r:38} R={r!r:22} U={u!r:14} F={f!r}")

    kept = parse.merge_wrapped(parse.content_rows(rows, geo.height))
    obs = parse.rows_to_observations(kept, page_no)
    print(f"\nafter filtering: {len(kept)} rows -> {len(obs)} observations")
    for o in obs:
        print(f"   {o.analyte:20} {o.value} {o.unit!r} flag={o.printed_flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "A"))
