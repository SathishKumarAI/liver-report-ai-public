"""The sample timeline: which specimen was drawn when, and on which pages.

Owns: turning raw band readings into a trustworthy list of samples, detecting
timestamps that OCR got wrong, repairing what can be repaired from other
evidence, and carrying sample context forward onto continuation pages.

Does NOT own: reading pixels (src/ocr.py) or interpreting lab values.

Why a whole module for this: the collection timestamp is the axis every chart is
drawn against. A single misread digit does not produce an obviously broken
value -- it produces a perfectly plausible date that silently files a day's
results in the wrong place. Two such errors were present in this document
(a month read 08 -> 06, and a day read 11 -> 13) and both looked like valid
dates. They are only detectable against the rest of the document.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

from . import config as C

# An inpatient admission produces samples on consecutive days. The valid window
# is therefore the contiguous run of days around the middle of the document,
# allowing a gap of at most this many days inside it.
#
# A fixed +/- N day window was tried first and is not enough: a day misread as
# 11 -> 13 lands only three days out and sits comfortably inside any window wide
# enough to be safe. Contiguity catches it, because the run 04..10 simply does
# not reach 13.
MAX_GAP_DAYS = 2


@dataclass
class Sample:
    sample_id: str | None
    collected: str | None
    acknowledged: str | None
    reported: str | None
    page: int
    date_suspect: bool = False
    repaired_from: str | None = None
    human_verified: bool = False

    def to_json(self) -> dict:
        return asdict(self)


def _day(iso: str) -> date:
    return datetime.fromisoformat(iso).date()


def _id_stem(sample_id: str | None) -> str | None:
    """Sample numbers differ only in a trailing check letter between aliquots of
    the same draw (SYN1000001A, SYN1000001A). The stem identifies the draw.

    OCR also confuses that trailing character (an A read as a 4), so the stem is
    the only part worth matching on.
    """
    if not sample_id:
        return None
    # Exactly seven digits: these IDs are 3 letters + 7 digits + an optional
    # check character. A greedy \d{5,8} swallowed a check digit that OCR had
    # turned from 'A' into '4', so SYN1000001A and SYN1000001A stopped matching.
    m = re.match(r"([A-Za-z]{2,4}\d{7})", sample_id)
    return m.group(1) if m else None


def find_window(records: list[dict]) -> tuple[date, date] | None:
    """The plausible collection-date range, derived from the document itself.

    Anchors on the modal month so a handful of corrupted readings cannot drag
    the window over to include themselves, then grows outward from the median
    day only while days stay contiguous.
    """
    days = [_day(r["collected"]) for r in records if r.get("collected")]
    if not days:
        return None

    modal_month = Counter((d.year, d.month) for d in days).most_common(1)[0][0]
    unique = sorted({d for d in days if (d.year, d.month) == modal_month})
    if not unique:
        return None

    anchor = unique[len(unique) // 2]
    i = unique.index(anchor)

    lo = i
    while lo > 0 and (unique[lo] - unique[lo - 1]).days <= MAX_GAP_DAYS:
        lo -= 1
    hi = i
    while hi < len(unique) - 1 and (unique[hi + 1] - unique[hi]).days <= MAX_GAP_DAYS:
        hi += 1

    return unique[lo], unique[hi]


def load_overrides(path=None) -> dict[int, dict]:
    """Human-verified band readings, keyed by page.

    Applied before anything else. A value a person read off the image is the
    best evidence available, so it must define the plausibility window rather
    than be tested against a window derived from unverified OCR.
    """
    path = path or (C.DATA / "overrides.json")
    if not path.exists():
        return {}
    blob = json.loads(path.read_text())
    return {int(k): v for k, v in blob.get("band_timestamps", {}).items()}


def reconcile(records: list[dict]) -> list[Sample]:
    """Flag out-of-window timestamps and repair them from sibling aliquots.

    Repair rule: two bands whose sample-number stems match are aliquots of the
    same draw and therefore share a collection time. This is evidence from the
    document, not an assumption -- it is why page 38's corrupted '2026-06-06'
    can be restored to page 40's verified '2024-03-06T02:14'.

    Anything that cannot be repaired keeps collected=None and date_suspect=True.
    It is never guessed: an unresolved timestamp is visible and fixable, while a
    guessed one is neither.
    """
    overrides = load_overrides()
    records = [dict(r) for r in records]
    for r in records:
        ov = overrides.get(r["page"])
        if ov:
            r.update(ov)
            r["human_verified"] = True

    window = find_window(records)
    samples = [Sample(
        sample_id=r.get("sample_id"),
        collected=r.get("collected"),
        acknowledged=r.get("acknowledged"),
        reported=r.get("reported"),
        page=r["page"],
        human_verified=bool(r.get("human_verified")),
    ) for r in records]

    if window:
        lo, hi = window
        for s in samples:
            if s.human_verified:
                continue
            if s.collected and not (lo <= _day(s.collected) <= hi):
                s.date_suspect = True
                s.collected = None

    # Build the trusted stem -> timestamp map from survivors only.
    trusted: dict[str, str] = {}
    for s in samples:
        stem = _id_stem(s.sample_id)
        if stem and s.collected and not s.date_suspect:
            trusted.setdefault(stem, s.collected)

    for s in samples:
        if s.collected:
            continue
        stem = _id_stem(s.sample_id)
        if stem and stem in trusted:
            s.collected = trusted[stem]
            s.repaired_from = f"aliquot:{stem}"

    return samples


def attach_pages(samples: list[Sample], total_pages: int) -> dict[int, Sample]:
    """Map every page to the sample it belongs to, carrying context forward.

    Roughly half the pages in this document are panel continuations with no band
    of their own (page 17 is a CBC continued from page 16). They inherit the last
    sample seen. Without this rule those pages contribute observations with no
    timestamp and drop out of every chart.
    """
    by_page = {s.page: s for s in samples}
    out: dict[int, Sample] = {}
    current: Sample | None = None
    for page in range(1, total_pages + 1):
        if page in by_page:
            current = by_page[page]
        if current is not None:
            out[page] = current
    return out


def load_and_reconcile(path=None) -> list[Sample]:
    path = path or (C.OCR_DIR / "bands.json")
    return reconcile(json.loads(path.read_text()))


if __name__ == "__main__":
    samples = load_and_reconcile()
    dated = [s for s in samples if s.collected]
    suspect = [s for s in samples if s.date_suspect]
    repaired = [s for s in samples if s.repaired_from]

    print(f"samples          : {len(samples)}")
    print(f"with a timestamp : {len(dated)}")
    print(f"flagged suspect  : {[s.page for s in suspect]}")
    print(f"repaired         : {[(s.page, s.collected, s.repaired_from) for s in repaired]}")
    print(f"days             : {sorted({s.collected[:10] for s in dated})}")

    pages = attach_pages(samples, 112)
    covered = [p for p, s in pages.items() if s.collected]
    print(f"pages with a resolved timestamp: {len(covered)} of 112")
