"""Check that the numbers quoted in the docs match the dataset they describe.

Prose drifts from data. A document that says bilirubin ended at 18.0 when the
dataset says 17.4 is worse than one that says nothing, because a reader has no
way to tell which is wrong.

This extracts the first->last claims made in docs/WHAT-THE-NUMBERS-MEAN.md and
compares them against data/labs.json.

    python tools/check_docs.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C  # noqa: E402

DOC = C.REPO / "docs" / "WHAT-THE-NUMBERS-MEAN.md"

# (analyte key, regex capturing the claimed first and last value)
CLAIMS = [
    ("bilirubin_total", r"Bilirubin\s*—\s*([\d.]+)\s*→\s*([\d.]+)\s*mg/dL"),
    ("ast", r"AST\s+([\d.]+)\s*→\s*([\d.]+)\s*U/L"),
    ("alt", r"ALT\s+([\d.]+)\s*→\s*([\d.]+)\s*U/L"),
    ("ammonia", r"Ammonia\s*—\s*([\d.]+)\s*→\s*[\d.]+\s*→\s*([\d.]+)\s*µmol/L"),
    ("urea", r"Urea\s*—\s*([\d.]+)(?:\s*→\s*[\d.]+)*\s*→\s*([\d.]+)\s*mg/dL"),
    ("sodium", r"Sodium\s*—\s*([\d.]+)\s*→\s*([\d.]+)\s*mEq/L"),
    ("procalcitonin", r"Procalcitonin\s*—\s*([\d.]+)\s*→\s*([\d.]+)\s*ng/mL"),
    ("hemoglobin", r"Haemoglobin\s+([\d.]+)\s*→\s*([\d.]+)\s*g/dL"),
    ("lactate", r"Lactate\s*—\s*([\d.]+)\s*→\s*([\d.]+)\s*mmol/L"),
    ("abg_po2", r"pO2\)\s*—\s*([\d.]+)\s*→\s*([\d.]+)\s*mmHg"),
    ("albumin", r"Albumin\s*—\s*([\d.]+)\s*g/dL"),
]


def series(dataset: dict, key: str) -> list[float]:
    rows = [o for o in dataset["observations"]
            if o.get("analyte") == key and o.get("value") is not None]
    rows.sort(key=lambda o: o["collected"])
    return [r["value"] for r in rows]


def main() -> int:
    if not C.LABS_JSON.exists():
        print("no dataset; run tools/make_synthetic.py first")
        return 1
    dataset = json.loads(C.LABS_JSON.read_text(encoding="utf-8"))
    text = DOC.read_text(encoding="utf-8")

    problems, checked = [], 0
    for key, pattern in CLAIMS:
        m = re.search(pattern, text)
        if not m:
            problems.append(f"{key}: no claim found matching {pattern!r}")
            continue
        vals = series(dataset, key)
        if not vals:
            problems.append(f"{key}: doc makes a claim but the dataset has no values")
            continue
        claimed = [float(g) for g in m.groups()]
        actual = [vals[0]] if len(claimed) == 1 else [vals[0], vals[-1]]
        checked += 1
        for c, a in zip(claimed, actual):
            if abs(c - a) > 0.05:
                problems.append(f"{key}: doc says {c}, dataset says {a}")

    # The score line must match too.
    meld = [r["meld_na"]["value"] for r in dataset.get("scores", [])
            if (r.get("meld_na") or {}).get("value") is not None]
    m = re.search(r"MELD-Na, day by day:\s*([\d\s·]+)", text)
    if m and meld:
        claimed = [int(x) for x in re.findall(r"\d+", m.group(1))]
        checked += 1
        if claimed != meld:
            problems.append(f"MELD-Na: doc says {claimed}, dataset says {meld}")

    print(f"claims checked : {checked}")
    if problems:
        print(f"\nFAIL - {len(problems)} mismatch(es):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nPASS - every number quoted in the guide matches the dataset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
