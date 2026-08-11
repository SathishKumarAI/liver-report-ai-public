"""Word boxes -> lab observations.

Owns: grouping OCR words into lines, assigning them to the report's four
columns by x position, rejoining names and units that wrap, and turning each
resulting row into an observation keyed to a canonical analyte.

Does NOT own: OCR (src/ocr.py), timestamps (src/samples.py), or deciding whether
a value is trustworthy (src/validate.py).

Why geometry rather than line text: on page 17 the analyte is printed as
"ABSOLUTE BASOPHIL" / "COUNT" across two lines and its unit as "10^3/mm^" / "3".
A parser that reads a line at a time sees a value whose name is half missing,
and the usual keyword-matching approach pairs it with the wrong analyte -- an
error that is well-formed, plausible and wrong, which is the worst kind here.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from . import config as C
from .ocr import Word

# Column boundaries as a fraction of page width, measured off this report
# template: TEST | RESULT | UNIT | BIOLOGICAL REF INTERVAL.
COL_RESULT = 0.29
COL_UNIT = 0.595
COL_REF = 0.695

# Lines that are structure or prose, never data. Everything from an
# "Interpretations:"/"Comments:" marker to the next sample band is commentary
# about the test, and contains numbers that would otherwise parse as results.
PROSE_MARKERS = re.compile(
    r"^(Method\s*[-:]|Interpretation|Comments?\s*:|Note\b|Report\s+Saved\s+By|"
    r"Sample\s*Type|Specimen\b|End\s+of\s+Report|Page\s+\d)", re.I)

# The patient identity box repeats on every page. Everything above the word
# "Facility" (its last row) is header, not results.
HEADER_ANCHOR = re.compile(r"Facilit", re.I)

# A result cell: a number, optionally preceded by a comparator, optionally
# followed by the lab's own high/low marker.
# The leading minus is NOT optional decoration. Base excess is routinely
# negative -- it is how metabolic acidosis is reported -- and dropping the sign
# turns "-3.9, acidotic" into "+3.9, alkalotic". Found by eye on the contact
# sheets: BE(B) -0.4 and BEecf -3.9 had both been recorded positive.
VALUE_RE = re.compile(r"^([<>]?)\s*(-?\d{1,7}(?:[.,]\d{1,4})?)$")
FLAG_RE = re.compile(r"\((C?[HL])\)|(?<![A-Za-z])([HL])(?![A-Za-z])")

QUALITATIVE = re.compile(
    r"^(POSITIVE|NEGATIVE|REACTIVE|NON[- ]?REACTIVE|PRESENT|ABSENT|NIL|"
    r"DETECTED|NOT\s+DETECTED|NORMAL|ADEQUATE)\b", re.I)


@dataclass
class Row:
    """One printed line, split into the report's four columns."""
    top: int
    bottom: int
    test: list[Word] = field(default_factory=list)
    result: list[Word] = field(default_factory=list)
    unit: list[Word] = field(default_factory=list)
    reference: list[Word] = field(default_factory=list)

    def text(self, which: str) -> str:
        return " ".join(w.text for w in getattr(self, which)).strip()

    @property
    def has_result(self) -> bool:
        return bool(self.result)


@dataclass
class Observation:
    analyte: str
    display: str
    kind: str                 # "quantity" | "qualitative"
    value: float | None
    text: str | None
    unit: str
    reference_text: str
    printed_flag: str | None
    page: int
    bbox: tuple[int, int, int, int]
    raw_test: str
    raw_value: str


def group_lines(words: list[Word], tolerance: float = 0.6) -> list[list[Word]]:
    """Cluster words into printed lines by vertical overlap.

    Tesseract's own line numbering is unreliable across the four columns of this
    template -- it frequently starts a new line group at a column boundary -- so
    lines are rebuilt from geometry.
    """
    if not words:
        return []

    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.top, w.left)):
        placed = False
        for line in lines:
            ref = line[0]
            overlap = min(w.bottom, ref.bottom) - max(w.top, ref.top)
            if overlap > tolerance * min(w.height, ref.height):
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])

    for line in lines:
        line.sort(key=lambda w: w.left)
    lines.sort(key=lambda line: min(w.top for w in line))
    return lines


def to_rows(lines: list[list[Word]], page_width: int) -> list[Row]:
    """Assign each word to a column by the x position of its centre."""
    rows: list[Row] = []
    for line in lines:
        row = Row(top=min(w.top for w in line), bottom=max(w.bottom for w in line))
        for w in line:
            centre = (w.left + w.width / 2) / page_width
            if centre < COL_RESULT:
                row.test.append(w)
            elif centre < COL_UNIT:
                row.result.append(w)
            elif centre < COL_REF:
                row.unit.append(w)
            else:
                row.reference.append(w)
        rows.append(row)
    return rows


def content_rows(rows: list[Word], page_height: int) -> list[Row]:
    """Drop the repeated patient header and everything after a prose marker."""
    start = 0
    for i, row in enumerate(rows):
        if HEADER_ANCHOR.search(row.text("test")) or HEADER_ANCHOR.search(row.text("unit")):
            start = i + 1
    kept = rows[start:]

    out: list[Row] = []
    skipping = False
    for row in kept:
        label = row.text("test")
        if PROSE_MARKERS.match(label):
            # "Method -" annotates the row above and stops there; the long
            # interpretation blocks run to the end of the panel.
            skipping = not label.lower().startswith("method")
            continue
        if skipping:
            # A row with a result column means the commentary has ended and the
            # next panel's data has begun.
            if row.has_result and _looks_like_value(row.text("result")):
                skipping = False
            else:
                continue
        out.append(row)
    return out


def _looks_like_value(text: str) -> bool:
    return bool(VALUE_RE.match(text.split()[0])) if text.split() else False


def merge_wrapped(rows: list[Row]) -> list[Row]:
    """Rejoin analyte names and units that the report wraps onto a second line.

    A row carrying only TEST-column text is a continuation of the row above it
    ("ABSOLUTE BASOPHIL" + "COUNT"). A row carrying only UNIT-column text is the
    tail of a wrapped unit ("10^3/mm^" + "3").
    """
    merged: list[Row] = []
    for row in rows:
        only_test = row.test and not (row.result or row.unit or row.reference)
        only_unit = row.unit and not (row.test or row.result or row.reference)

        if merged and only_test and not merged[-1].has_result:
            # Name continued before the value appeared: keep accumulating.
            merged[-1].test.extend(row.test)
            merged[-1].bottom = row.bottom
            continue
        if merged and only_unit:
            merged[-1].unit.extend(row.unit)
            merged[-1].bottom = row.bottom
            continue
        if merged and only_test and merged[-1].has_result:
            # Name continued AFTER the value's line -- the report does this for
            # two-line analyte names whose value sits on the first line.
            merged[-1].test.extend(row.test)
            merged[-1].bottom = row.bottom
            continue
        merged.append(row)
    return merged


def _clean_label(text: str) -> str:
    text = re.sub(r"[,;:]+$", "", text.strip())
    text = re.sub(r"\s*,\s*(Serum|Plasma|Blood|serum|plasma)\s*$", "", text)
    return text.strip()


# Below this similarity a near-match is refused. Set high on purpose: mapping a
# value onto the WRONG analyte is far worse than dropping it, because a dropped
# value is visible in the coverage count while a mismapped one is invisible.
FUZZY_CUTOFF = 0.86


def match_analyte(label: str) -> str | None:
    """Map a printed test name to a canonical analyte key.

    Exact match first, then leading-word prefixes (a wrapped name that picked up
    a stray word still resolves), then a similarity fallback.

    The similarity step is needed because the scan's punch-hole clips the first
    character of names in the left column: "PROTHROMBIN TIME" arrives as
    ">ROTHROMBIN TIME" and matches nothing exactly.
    """
    cleaned = _clean_label(label)
    normed = C._norm(cleaned)
    key = C.ALIAS_TO_KEY.get(normed)
    if key:
        return key

    words = cleaned.split()
    for n in range(len(words), 0, -1):
        key = C.ALIAS_TO_KEY.get(C._norm(" ".join(words[:n])))
        if key:
            return key

    if len(normed) >= 5:
        close = difflib.get_close_matches(normed, C.ALIAS_TO_KEY.keys(),
                                          n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return C.ALIAS_TO_KEY[close[0]]
    return None


def parse_value(text: str) -> tuple[float | None, str | None, str]:
    """Split a result cell into (number, printed flag, raw text)."""
    raw = text.strip()
    flag = None
    m = FLAG_RE.search(raw)
    if m:
        flag = (m.group(1) or m.group(2) or "").upper() or None

    # Strip the flag and its arrow glyph, then take the first numeric token.
    stripped = FLAG_RE.sub(" ", raw)
    stripped = re.sub(r"[▲▼^v]", " ", stripped)
    # OCR often separates the sign from its digits ("- 3.9"); rejoin before
    # tokenising so the minus is not lost as a stray word.
    stripped = re.sub(r"(?<![\d.])-\s+(?=\d)", "-", stripped)
    for token in stripped.split():
        vm = VALUE_RE.match(token)
        if vm:
            try:
                return float(vm.group(2).replace(",", ".")), flag, raw
            except ValueError:
                continue
    return None, flag, raw


def rows_to_observations(rows: list[Row], page: int) -> list[Observation]:
    out: list[Observation] = []
    for row in rows:
        label = row.text("test")
        if not label or not row.has_result:
            continue
        key = match_analyte(label)
        if not key:
            continue

        meta = C.ANALYTES[key]
        result_text = row.text("result")
        value, flag, raw = parse_value(result_text)

        boxes = row.result
        bbox = (min(w.left for w in boxes), min(w.top for w in boxes),
                max(w.right for w in boxes) - min(w.left for w in boxes),
                max(w.bottom for w in boxes) - min(w.top for w in boxes))

        if value is None:
            # Everything in ANALYTES is a measured quantity. A non-numeric cell
            # against one of these keys is not a result -- it is the peripheral
            # smear's prose ("PLATELETS  Adequate giant platelets seen"), which
            # would otherwise land as a second, empty platelet observation.
            # Genuinely qualitative results (cultures, serology) are handled by
            # their own path and are not in this dictionary.
            continue

        out.append(Observation(
            analyte=key, display=meta["display"], kind="quantity",
            value=value, text=None, unit=row.text("unit"),
            reference_text=row.text("reference"), printed_flag=flag,
            page=page, bbox=bbox, raw_test=label, raw_value=result_text))
    return out


def parse_page(words: list[Word], page: int, width: int, height: int) -> list[Observation]:
    rows = to_rows(group_lines(words), width)
    rows = content_rows(rows, height)
    rows = merge_wrapped(rows)
    return rows_to_observations(rows, page)
