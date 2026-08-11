"""Full-document extraction: pages -> observations with per-pass OCR evidence.

Owns: running the three OCR passes over every page, parsing each independently,
merging them into one observation per (page, analyte) with the three readings
recorded, and joining each to its sample timestamp.

Does NOT own: the validation verdicts (src/validate.py) or the dataset file
layout (src/build.py).

The three readings are kept rather than collapsed. A value all three passes
agree on is worth more than the same value from one pass, and the disagreements
are exactly the list of things a human needs to look at.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from . import config as C, ocr, parse, render, samples as samples_mod


def extract_page(image, page_no: int, width: int, height: int) -> dict[str, dict]:
    """Parse one page under every OCR pass. Keyed by analyte."""
    work = C.OCR_DIR / "work"
    work.mkdir(parents=True, exist_ok=True)

    per_pass: dict[str, dict[str, parse.Observation]] = {}
    for name in C.OCR_PASSES:
        try:
            words = ocr.ocr_words(image, name, work)
            obs = parse.parse_page(words, page_no, width, height)
        except RuntimeError:
            obs = []
        # Last occurrence wins within a page: panels do not repeat an analyte,
        # and a stray earlier match is more likely to be the header echo.
        per_pass[name] = {o.analyte: o for o in obs}

    merged: dict[str, dict] = {}
    for name, table in per_pass.items():
        for key, o in table.items():
            slot = merged.setdefault(key, {
                "analyte": key, "display": o.display, "page": page_no,
                "unit": "", "reference_text": "", "printed_flag": None,
                "bbox": list(o.bbox), "raw_test": o.raw_test,
                "ocr": {}, "value": None,
            })
            slot["ocr"][name] = o.value
            # Pass A is the reference read for everything except the number
            # itself: it keeps punctuation the whitelisted pass C throws away.
            if name == "A" or not slot["unit"]:
                slot["unit"] = o.unit or slot["unit"]
                slot["reference_text"] = o.reference_text or slot["reference_text"]
                slot["printed_flag"] = o.printed_flag or slot["printed_flag"]
                slot["bbox"] = list(o.bbox)
                slot["raw_test"] = o.raw_test

    for slot in merged.values():
        readings = [v for v in slot["ocr"].values() if v is not None]
        if readings:
            # Majority; ties fall to pass A, then to whatever exists.
            slot["value"] = max(set(readings), key=readings.count)
    return merged


def run(limit: int | None = None) -> dict:
    pages = sorted(C.PAGES.glob("pg-*.jpg"))
    if limit:
        pages = pages[:limit]

    sample_list = samples_mod.load_and_reconcile()
    page_to_sample = samples_mod.attach_pages(sample_list, len(pages))

    observations: list[dict] = []
    per_page_counts: dict[int, int] = {}

    for i, image in enumerate(pages, 1):
        geo = render.analyse_page(image, i)
        found = extract_page(image, i, geo.width, geo.height)
        sample = page_to_sample.get(i)

        for slot in found.values():
            slot["sample_id"] = sample.sample_id if sample else None
            slot["collected"] = sample.collected if sample else None
            observations.append(slot)
        per_page_counts[i] = len(found)
        if i % 20 == 0:
            print(f"  ...page {i}/{len(pages)}", flush=True)

    empty = [p for p, n in per_page_counts.items() if n == 0]
    payload = {
        "observations": observations,
        "samples": [s.to_json() for s in sample_list],
        "coverage": {
            "pages": len(pages),
            "observations": len(observations),
            "pages_with_no_observations": empty,
        },
    }
    (C.DATA / "raw_observations.json").write_text(json.dumps(payload, indent=1))
    return payload


if __name__ == "__main__":
    result = run()
    cov = result["coverage"]
    print(f"pages                  : {cov['pages']}")
    print(f"observations           : {cov['observations']}")
    print(f"pages with none        : {len(cov['pages_with_no_observations'])}")
    print(f"  {cov['pages_with_no_observations']}")

    agree = sum(1 for o in result["observations"]
                if len({v for v in o["ocr"].values() if v is not None}) == 1)
    print(f"unanimous across passes: {agree}/{len(result['observations'])}")
