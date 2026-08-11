"""PDF pages -> JPEGs, and the geometry of each page's dark bands.

Owns: calling pdftoppm, row-luminance profiling, classifying dark runs into the
two bands that matter (column header, sample metadata), and deriving column
x-boundaries from the header band.

Does NOT own: reading any text. Nothing here runs OCR. It answers only "where on
this page is the structure", which is what makes the OCR stage reliable.

Why row luminance: the sample band is white text on mid-grey. Tesseract
binarises it away completely -- a sweep for "Sample No" across all 112 pages of
this document matched zero times. Finding the band geometrically, then inverting
just that strip, is what recovers the collection timestamp. See docs/OCR-NOTES.md.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config as C


@dataclass
class Band:
    """A horizontal dark strip on a page, in pixel rows."""
    top: int
    bottom: int
    kind: str          # "header" | "sample" | "unknown"

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1


@dataclass
class PageGeometry:
    page: int
    path: str
    width: int
    height: int
    bands: list[Band]
    columns: dict[str, float] | None   # x boundaries, fraction of page width

    def to_json(self) -> dict:
        d = asdict(self)
        d["bands"] = [asdict(b) for b in self.bands]
        return d


def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr.strip()[:400]}")
    return r.stdout


def render_pages(pdf: Path, out_dir: Path, dpi: int = C.RENDER_DPI) -> list[Path]:
    """Render every page to JPEG. Idempotent: existing renders are left alone.

    Idempotence is what makes incremental ingest cheap -- adding tomorrow's
    report re-renders only its pages.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / "pg"
    existing = sorted(out_dir.glob("pg-*.jpg"))
    if not existing:
        _run([C.PDFTOPPM, "-r", str(dpi), "-jpeg",
              "-jpegopt", f"quality={C.JPEG_QUALITY}", str(pdf), str(stem)])
        existing = sorted(out_dir.glob("pg-*.jpg"))
    return existing


def row_luminance(image: Path) -> list[int]:
    """Mean grey level of every pixel row, top to bottom.

    `-resize 1x!` collapses the image to a single column, so each output pixel
    IS the mean of one row. This is the numpy-free way to profile a page, and
    the reason the pipeline needs no scientific stack at all.
    """
    txt = _run([C.MAGICK, str(image), "-colorspace", "gray", "-resize", "1x!", "txt:-"])
    rows: list[int] = []
    for line in txt.splitlines()[1:]:
        m = re.match(r"^0,(\d+):\s*\((\d+)", line)
        if m:
            rows.append(int(m.group(2)))
    return rows


def image_size(image: Path) -> tuple[int, int]:
    out = _run([C.MAGICK, "identify", "-format", "%w %h", str(image)]).split()
    return int(out[0]), int(out[1])


def find_dark_runs(rows: list[int], height: int) -> list[tuple[int, int]]:
    """Contiguous runs of dark rows that are plausibly a filled band.

    Two filters, and both are needed. Height rejects lines of body text; mean
    darkness rejects the bold underlined sub-headings that are tall enough to
    pass the height filter. Darkness alone was tried first and produced phantom
    bands out of the dense italic "Comments:" paragraph -- see config.

    The top slice of the page is skipped: CamScanner leaves a black sheet edge
    there that is not a band and would otherwise be the darkest run found.
    """
    start_y = int(height * C.BAND_SEARCH_TOP_FRAC)
    runs: list[tuple[int, int]] = []
    run_start: int | None = None

    for y in range(start_y, len(rows)):
        dark = rows[y] < C.DARK_ROW_MAX
        if dark and run_start is None:
            run_start = y
        elif not dark and run_start is not None:
            runs.append((run_start, y - 1))
            run_start = None
    if run_start is not None:
        runs.append((run_start, len(rows) - 1))

    lo = height * C.BAND_MIN_HEIGHT_FRAC
    hi = height * C.BAND_MAX_HEIGHT_FRAC
    keep = []
    for a, b in runs:
        run_h = b - a + 1
        if not (lo <= run_h <= hi):
            continue
        segment = rows[a:b + 1]
        if sum(segment) / len(segment) > C.BAND_MAX_MEAN_LUM:
            continue
        keep.append((a, b))
    return keep


def classify_bands(runs: list[tuple[int, int]]) -> list[Band]:
    """Label dark runs.

    The two bands always appear as a close-together pair: the column header
    (TEST | RESULT | UNIT | BIOLOGICAL REF INTERVAL) sits immediately above the
    sample metadata band (Sample No | Collection Date | Ack Date | Report Date).
    A run whose next neighbour starts within roughly two band-heights is the
    header of that pair; the neighbour is the sample band.

    Everything else -- table rules, underlines, the signature block -- stays
    "unknown" and is ignored downstream.
    """
    bands: list[Band] = []
    i = 0
    while i < len(runs):
        top, bottom = runs[i]
        height = bottom - top + 1
        if i + 1 < len(runs):
            next_top, next_bottom = runs[i + 1]
            gap = next_top - bottom
            if 0 <= gap <= max(30, height * 3):
                bands.append(Band(top, bottom, "header"))
                bands.append(Band(next_top, next_bottom, "sample"))
                i += 2
                continue
        bands.append(Band(top, bottom, "unknown"))
        i += 1
    return bands


# Column boundaries as a fraction of page width. Measured from the printed
# header band on this report template: TEST | RESULT | UNIT | BIOLOGICAL REF
# INTERVAL. Held here as fractions so they survive any render DPI change.
#
# ponytail: fixed fractions, not read from the header band's own word positions.
# Every page in this document uses one template, so measuring per page buys
# nothing today. If a second hospital's layout ever lands here, derive these
# from the header band's OCR instead -- the band is already located for it.
COLUMN_FRACTIONS = {
    "test": 0.00,
    "result": 0.32,
    "unit": 0.60,
    "reference": 0.72,
    "end": 1.00,
}


def analyse_page(image: Path, page_no: int) -> PageGeometry:
    width, height = image_size(image)
    rows = row_luminance(image)
    bands = classify_bands(find_dark_runs(rows, height))
    return PageGeometry(
        page=page_no,
        path=str(image),
        width=width,
        height=height,
        bands=bands,
        columns=dict(COLUMN_FRACTIONS),
    )


def analyse_all(pages: list[Path]) -> list[PageGeometry]:
    return [analyse_page(p, i + 1) for i, p in enumerate(pages)]


if __name__ == "__main__":
    # Self-check: page 40 is the page whose band was read by hand and confirmed
    # against the image (Collection Date 06/03/24 02:14). If band detection
    # stops finding a sample band there, this stage is broken.
    imgs = render_pages(next(C.RAW.glob("*.pdf")), C.PAGES)
    print(f"pages rendered: {len(imgs)}")
    geo = analyse_page(imgs[39], 40)
    kinds = [b.kind for b in geo.bands]
    print(f"p40 size={geo.width}x{geo.height} bands={kinds}")
    assert "sample" in kinds, "p40 must have a detectable sample band"
    print("OK")
