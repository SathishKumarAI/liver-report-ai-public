"""Tesseract driver: page images -> word boxes.

Owns: running tesseract, the three decorrelated passes, parsing TSV into Word
records, and the separate inverted read of the grey metadata bands.

Does NOT own: deciding what any word means. No analyte names, no clinical
vocabulary, no validation. This module answers only "what glyphs are where".

Why three passes rather than one: a single OCR read gives no way to know when it
is wrong. Three reads with different preprocessing fail differently, so
disagreement becomes a signal. Pass C additionally restricts the character set to
digits, which makes the classic O/0, l/1, S/5, B/8 substitutions impossible by
construction rather than merely unlikely.
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config as C


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float
    line: int          # tesseract's own line grouping, kept as a hint

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def cy(self) -> float:
        return self.top + self.height / 2


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    # encoding must be forced: Windows defaults these pipes to cp1252 while
    # tesseract emits UTF-8, and a single degree sign or dash in the OCR output
    # then raises UnicodeDecodeError from a reader thread. errors="replace"
    # keeps one unreadable glyph from destroying a whole page's read.
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {(r.stderr or '').strip()[:400]}")
    return r


def _preprocess(image: Path, mode: str, work: Path) -> Path:
    """Produce the variant of the page a given pass reads.

    'gray'  - plain desaturation; tesseract does its own binarisation.
    'otsu'  - we binarise instead, with a different algorithm than tesseract's,
              so this pass makes different mistakes. That independence is the
              whole point; a second pass that fails identically buys nothing.
    """
    if mode == "gray":
        out = work / f"{image.stem}_gray.png"
        args = ["-colorspace", "gray", "-normalize"]
    elif mode == "otsu":
        out = work / f"{image.stem}_otsu.png"
        args = ["-colorspace", "gray", "-auto-level", "-threshold", "62%"]
    else:
        raise ValueError(f"unknown preprocess mode {mode!r}")

    if not out.exists():
        _run([C.MAGICK, str(image), *args, str(out)])
    return out


def _tsv_to_words(tsv: str) -> list[Word]:
    words: list[Word] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row["conf"])
            if conf < 0:            # tesseract uses -1 for non-text blocks
                continue
            words.append(Word(
                text=text,
                left=int(row["left"]), top=int(row["top"]),
                width=int(row["width"]), height=int(row["height"]),
                conf=conf,
                line=int(row["line_num"]),
            ))
        except (KeyError, ValueError):
            continue
    return words


def ocr_words(image: Path, pass_name: str, work: Path) -> list[Word]:
    """Run one configured pass over a full page and return its word boxes."""
    cfg = C.OCR_PASSES[pass_name]
    src = _preprocess(image, cfg["preprocess"], work)

    cmd = [C.TESSERACT, str(src), "stdout", "--psm", cfg["psm"], "-l", "eng"]
    if "whitelist" in cfg:
        cmd += ["-c", f"tessedit_char_whitelist={cfg['whitelist']}"]
    cmd += ["tsv"]
    return _tsv_to_words(_run(cmd).stdout)


def ocr_region(image: Path, box: tuple[int, int, int, int], work: Path,
               psm: str = "7", whitelist: str | None = None,
               invert: bool = False, scale_str: str = "300%") -> str:
    """OCR a single rectangle. Used for the grey bands and for re-reading a
    disputed value from its own crop.

    `invert` exists for the sample band specifically: it is white text on a
    mid-grey fill, and tesseract assumes the opposite polarity. Without the
    negation the band is simply invisible -- a sweep for "Sample No" across all
    112 pages of this document matched zero times before this path existed.
    """
    x, y, w, h = box
    tmp = work / f"{image.stem}_r{x}_{y}_{w}_{h}_{int(invert)}_{scale_str.strip('%')}_{psm}.png"
    if not tmp.exists():
        args = [C.MAGICK, str(image), "-crop", f"{w}x{h}+{x}+{y}", "+repage",
                "-colorspace", "gray", "-resize", scale_str]
        if invert:
            args += ["-negate", "-normalize", "-level", "20%,80%", "-sharpen", "0x1"]
        else:
            args += ["-normalize", "-sharpen", "0x1"]
        args += [str(tmp)]
        _run(args)

    cmd = [C.TESSERACT, str(tmp), "stdout", "--psm", psm, "-l", "eng"]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    return _run(cmd).stdout.strip()


# --------------------------------------------------------------------------
# Grey metadata band -> sample identity and timestamps.
# --------------------------------------------------------------------------

# The band OCRs noisily even after inversion -- separator glyphs and stray
# punctuation land between fields. Anchor on the field LABELS and take the first
# date-like token after each, rather than trying to clean the whole string.
_BAND_DATE = r"(\d{2})[/\-](\d{2})[/\-](\d{2,4})\s*[.,]?\s*(\d{1,2})[:.;](\d{2})"

# OCR sprinkles punctuation through the band ("Sample.No-“SYN1000001A"), so the
# separator between label and value must be permissive. The ID itself is a
# strict shape though -- 2-4 letters, then 6-9 digit-like glyphs, then an
# optional check letter -- and pinning that shape is what stops the regex from
# swallowing the following "Collection" text.
# OCR inserts stray glyphs inside the label itself ("Sample e.No.\/SYN1000001A"),
# so allow noise between "Sample" and "No" as well as after it.
_SAMPLE_NO = re.compile(
    r"Sample\s*[^A-Za-z0-9]{0,4}\s*No[^A-Za-z0-9]{0,6}([A-Za-z]{2,4}[0-9IiOolLSs]{6,9}[A-Za-z]?)")

# Field labels in the order they are printed. Segmenting the band by these, and
# searching only within a field's own segment, is what stops a garbled field
# from picking up its neighbour's timestamp -- an earlier version took the
# Report Date as the Ack Date whenever "Ack Date" OCR'd badly.
_BAND_LABELS = [
    ("sample_no", r"Sample\s*\.?\s*No"),
    ("collected", r"Coll?ect[a-z]*\s*Date"),
    ("acknowledged", r"Ack\w*\s*Date"),
    ("reported", r"Repor?t\w*\s*Date"),
]


def _segment_band(text: str) -> dict[str, str]:
    """Split a band reading into one text segment per printed field."""
    found = []
    for key, pattern in _BAND_LABELS:
        m = re.search(pattern, text, re.I)
        if m:
            found.append((m.start(), m.end(), key))
    found.sort()

    segments: dict[str, str] = {}
    for i, (_start, end, key) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(text)
        segments[key] = text[end:stop]
    return segments


_BAND_DATE_ONLY = r"(\d{2})[/\-](\d{2})[/\-](\d{2,4})"


def _parse_datetime(segment: str, require_time: bool = True) -> str | None:
    """Return ISO 'YYYY-MM-DDTHH:MM' for the first timestamp in a segment.

    `require_time=False` accepts a bare date and reports midnight. Used only for
    the acknowledged/reported fields, where the clock time is informational.
    The collection timestamp always requires a real time: it orders the whole
    dataset, and a silent midnight would reshuffle the day boundaries.
    """
    d = re.search(_BAND_DATE, segment)
    if not d:
        if require_time:
            return None
        d2 = re.search(_BAND_DATE_ONLY, segment)
        if not d2:
            return None
        day, month, year = d2.groups()
        return _assemble(day, month, year, "00", "00")
    return _assemble(*d.groups())


def _assemble(day: str, month: str, year: str, hh: str, mm: str) -> str | None:
    year = year if len(year) == 4 else f"20{year}"
    try:
        di, mi, yi, hi, mi2 = int(day), int(month), int(year), int(hh), int(mm)
    except ValueError:
        return None
    # Sanity: this is a date, not a lab value that happens to look like one.
    if not (1 <= di <= 31 and 1 <= mi <= 12 and 2000 <= yi <= 2100
            and 0 <= hi <= 23 and 0 <= mi2 <= 59):
        return None
    return f"{yi:04d}-{mi:02d}-{di:02d}T{hi:02d}:{mi2:02d}"


# The band is read one FIELD AT A TIME, not as a whole strip.
#
# Reading the full band is unreliable: it is roughly 2480x63 px, and after
# upscaling becomes a ~5000 px wide, ~130 px tall ribbon that tesseract reads
# well on some pages and not at all on others. Measured over the document, the
# whole-strip approach recovered a collection timestamp on only 7 of 55 bands.
# Cropping each field to its own narrow window fixes it -- the same page that
# returned nothing as a strip reads perfectly as four windows.
#
# Each window starts at its own label and runs into the next, so the first
# date-like token after the label belongs to that field.
#
# NOTE: do NOT add tessedit_char_whitelist here. These windows contain the field
# LABEL as well as the value, and whitelisting to digits makes tesseract return
# an empty string rather than skipping the letters. That mistake is what made an
# earlier version of this function look unfixable.
# Windows overlap generously. Measured on this template: the "Ack Date" label
# sits around x=0.48-0.53 and "Report Date" around x=0.70-0.75, so a window that
# starts at the label's own left edge clips it and loses the anchor.
# The printed band does not reach the page edge -- it starts around x=0.035 and
# ends around x=0.965. A window that runs to 0.00 or 1.00 therefore includes
# white paper margin, which after the inversion becomes a black slab and makes
# tesseract return nothing. Both end fields failed on every page and every scale
# until these were pulled inside the band.
BAND_FIELD_WINDOWS = {
    "sample_no":    (0.04, 0.30),
    "collected":    (0.22, 0.54),
    "acknowledged": (0.44, 0.76),
    "reported":     (0.66, 0.96),
}

# (psm, scale) combinations tried per field until one parses.
#
# No single combination reads all four fields. Measured on page 40: the sample
# number only comes out under psm 8 (treat as one word), while the report date
# only comes out under psm 6 (uniform block) -- psm 7 returns empty for both yet
# reads the collection and acknowledgement times cleanly. Rather than pick a
# compromise that half-works, try in order and stop at the first field that
# parses. Most fields resolve on the first or second attempt.
BAND_ATTEMPTS = [
    ("6", "150%"),
    ("7", "150%"),
    ("8", "150%"),
    ("6", "300%"),
    ("8", "300%"),
    ("6", "100%"),
]


def read_band(image: Path, band, page_width: int, work: Path) -> dict:
    """Extract sample identity and the three timestamps from one grey band.

    Runs several crop/scale variants and keeps the first valid reading for each
    field independently. A field nobody reads stays None rather than being
    guessed -- a wrong collection timestamp would silently move an observation
    to the wrong day, which is worse than a missing one we can flag.
    """
    label_for = dict(_BAND_LABELS)
    votes: dict[str, list[str]] = {k: [] for k in BAND_FIELD_WINDOWS}
    raws: list[str] = []

    date_only: dict[str, str] = {}

    for field, (x0, x1) in BAND_FIELD_WINDOWS.items():
        left = int(page_width * x0)
        width = int(page_width * (x1 - x0))

        for psm, scale in BAND_ATTEMPTS:
            raw = ocr_region(image, (left, band.top, width, band.height), work,
                             psm=psm, invert=True, scale_str=scale)
            raws.append(f"{field}@{psm}/{scale}:{raw}")

            # Anchor on this field's own label; the window begins there, so the
            # first timestamp after it is this field's, not a neighbour's.
            m = re.search(label_for[field], raw, re.I)
            tail = raw[m.end():] if m else raw

            if field == "sample_no":
                sid = _SAMPLE_NO.search(raw)
                if sid:
                    votes[field].append(sid.group(1))
                continue

            # Always prefer a reading that includes a clock time. An earlier
            # version stopped at the first attempt that parsed at all, so a
            # date-only read from psm 6 won over the correct 05:23 that psm 7
            # would have produced one attempt later.
            timed = _parse_datetime(tail, require_time=True)
            if timed:
                votes[field].append(timed)
                break
            if field != "collected" and field not in date_only:
                fallback = _parse_datetime(tail, require_time=False)
                if fallback:
                    date_only[field] = fallback

    def majority(values: list[str]) -> str | None:
        return max(set(values), key=values.count) if values else None

    return {
        "sample_id": _best_sample_id(votes["sample_no"]),
        "collected": majority(votes["collected"]),
        "acknowledged": majority(votes["acknowledged"]) or date_only.get("acknowledged"),
        "reported": majority(votes["reported"]) or date_only.get("reported"),
        "votes": votes,
        "raw": " | ".join(raws),
    }


def _best_sample_id(candidates: list[str]) -> str | None:
    """Pick and repair the sample number from the variant readings.

    These IDs are an alphabetic prefix followed by digits and a check letter.
    OCR reliably renders the digit 1 in the numeric body as capital I
    (SYN1000001A comes back as AGII955943A), so I->1 and O->0 after the prefix
    is a safe, reversible repair. Longest reading wins: the failure mode here is
    dropped characters, not invented ones.
    """
    if not candidates:
        return None
    best = max(candidates, key=len)
    if len(best) > 3:
        best = best[:3] + best[3:].replace("I", "1").replace("O", "0")
    return best


if __name__ == "__main__":
    # Ground truth: page 40's band was read by eye from the image as
    # Collection 06/03/24 02:14, Ack 06/03/2024 05:23, Report 06/03/24 08:36.
    from . import render

    work = C.OCR_DIR / "work"
    work.mkdir(parents=True, exist_ok=True)
    page = sorted(C.PAGES.glob("pg-*.jpg"))[39]
    geo = render.analyse_page(page, 40)
    band = next(b for b in geo.bands if b.kind == "sample")

    got = read_band(page, band, geo.width, work)
    print(f"sample_id    {got['sample_id']}")
    print(f"collected    {got['collected']}")
    print(f"acknowledged {got['acknowledged']}")
    print(f"reported     {got['reported']}")
    assert got["collected"] == "2024-03-06T02:14", got["collected"]
    assert got["acknowledged"] == "2024-03-06T05:23", got["acknowledged"]
    assert got["reported"] == "2024-03-06T08:36", got["reported"]

    words = ocr_words(page, "A", work)
    print(f"pass A words on p40: {len(words)}")
    assert any(w.text == "34.3" for w in words), "PT value missing from pass A"
    print("OK")
