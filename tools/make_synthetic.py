"""Generate a wholly fabricated dataset so the dashboard can be demonstrated.

Not de-identified real data -- INVENTED data. There is no transformation of a
real value anywhere in this file, so there is nothing to re-identify. That is a
stronger guarantee than anonymisation, and it is the only one worth making for
a public repository.

The numbers are clinically shaped rather than random: a synthetic case of
acute-on-chronic liver failure, because a dashboard demonstrated on noise shows
nothing about whether it works. Shape is borrowed from published reference
ranges and textbook trajectories, not from any individual.

    python tools/make_synthetic.py            # writes data/labs.json
    python tools/make_synthetic.py --out X    # elsewhere
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C, patterns, scores, validate  # noqa: E402

# A fixed, obviously-synthetic start date well away from any real admission.
START = date(2024, 3, 4)
DAYS = 8

# analyte -> per-day values. None means "not measured that day", which is the
# realistic case and the one the pipeline has to survive.
SERIES: dict[str, list] = {
    "bilirubin_total":  [14.6, None, 16.1, None, 17.4, None, 18.0, None],
    "bilirubin_direct": [8.1, None, 9.0, None, 9.7, None, 10.1, None],
    "bilirubin_indirect": [6.5, None, 7.1, None, 7.7, None, 7.9, None],
    "ast":              [312, None, None, None, 268, None, None, None],
    "alt":              [96, None, None, None, 81, None, None, None],
    "alp":              [104, None, None, None, None, None, None, None],
    "albumin":          [2.7, None, None, None, None, None, None, None],
    "globulin":         [3.9, None, None, None, None, None, None, None],
    "protein_total":    [6.6, None, None, None, None, None, None, None],
    "ag_ratio":         [0.69, None, None, None, None, None, None, None],
    "ammonia":          [64, None, 72, None, None, 79, None, None],

    "pt":               [38.2, None, 30.1, None, 27.4, None, 28.9, None],
    "pt_mnpt":          [12.0, None, 12.0, None, 12.0, None, 12.0, None],
    "inr":              [3.18, None, 2.51, None, 2.28, None, 2.41, None],
    "platelets":        [148, None, 143, None, 139, None, 131, None],

    "creatinine":       [1.74, None, 1.42, 1.51, None, 1.66, None, 2.58],
    "urea":             [46, None, 55, 61, None, 78, None, 96],
    "sodium":           [130, None, 134, 137, None, 138, None, 136],
    "potassium":        [3.7, None, 4.0, 4.1, None, 4.4, None, 4.3],
    "chloride":         [98, None, 101, 103, None, 104, None, 105],
    "calcium":          [8.3, None, None, None, None, 7.9, None, None],
    "magnesium":        [2.5, None, None, None, None, 2.6, None, None],
    "phosphorus":       [1.4, None, 1.1, None, 3.8, None, None, 5.2],

    "hemoglobin":       [11.8, None, 11.5, None, 11.9, None, 11.2, None],
    "rbc":              [3.42, None, 3.35, None, 3.44, None, 3.21, None],
    "pcv":              [34.1, None, 33.4, None, 34.0, None, 31.8, None],
    "mcv":              [99.7, None, 99.7, None, 98.8, None, 99.1, None],
    "mch":              [34.5, None, 34.3, None, 34.6, None, 34.9, None],
    "mchc":             [34.6, None, 34.4, None, 35.0, None, 35.2, None],
    "rdw":              [13.9, None, 14.2, None, None, None, 14.4, None],
    "mpv":              [12.4, None, 12.6, None, 12.9, None, 12.8, None],
    "wbc":              [11800, None, 9900, None, 14600, None, 19100, None],
    "neutrophils_pct":  [78.4, None, 79.9, None, 85.1, None, 89.6, None],
    "lymphocytes_pct":  [11.2, None, 9.4, None, 7.1, None, 5.2, None],
    "monocytes_pct":    [9.1, None, 9.6, None, 7.2, None, 4.8, None],
    "eosinophils_pct":  [1.0, None, 0.8, None, 0.5, None, 0.3, None],
    "basophils_pct":    [0.3, None, 0.3, None, 0.1, None, 0.1, None],
    "anc":              [9251, None, 7910, None, 12423, None, 17114, None],
    "alc":              [1322, None, 931, None, 1037, None, 993, None],
    "amc":              [1074, None, 950, None, 1051, None, 917, None],
    "aec":              [118, None, 79, None, 73, None, 57, None],
    "abc":              [35, None, 30, None, 15, None, 19, None],
    "nlr":              [7.0, None, 8.5, None, 12.0, None, 17.2, None],

    "procalcitonin":    [4.11, None, None, None, 2.06, None, None, None],
    "crp":              [58.2, None, None, None, None, None, None, None],
    "il6":              [None, None, None, None, 142, None, None, None],

    "abg_ph":           [7.44, 7.47, 7.42, 7.45, 7.40, 7.41, 7.38, 7.42],
    "abg_pco2":         [36, 29, 33, 35, 34, 33, 35, 34],
    "abg_po2":          [58, 84, 96, 88, 91, 103, 99, 97],
    "abg_hco3":         [24.1, 23.4, 23.0, 22.8, 22.1, 21.9, 21.4, 21.8],
    "abg_be":           [0.4, 0.8, -0.6, -1.1, -2.0, -2.4, -3.1, -2.7],
    "lactate":          [3.2, 2.4, 2.0, 1.8, 2.6, 1.6, 2.2, 1.5],
    "abg_sodium":       [131, 132, 134, 136, 137, 138, 136, 137],
    "abg_potassium":    [3.6, 3.9, 4.0, 4.2, 4.3, 4.1, 4.4, 4.2],
    "abg_chloride":     [99, 100, 102, 103, 104, 105, 104, 105],
    "abg_calcium":      [4.18, 4.09, 4.21, 4.02, 3.96, 4.11, 4.05, 4.14],
    "abg_hct":          [37, 36, 35, 34, 33, 32, 31, 32],
    "abg_glucose":      [148, 131, 126, 139, 144, 137, 129, 133],
    "abg_thb":          [12.6, 12.2, 11.9, 11.6, 11.3, 11.0, 10.8, 11.1],
    "abg_o2hb":         [88.4, 94.1, 95.8, 95.2, 95.6, 96.4, 96.0, 96.2],
    "abg_cohb":         [1.4, 1.6, 1.5, 1.3, 1.7, 1.5, 1.6, 1.4],
    "abg_methb":        [0.9, 1.1, 1.0, 0.8, 1.2, 0.9, 1.0, 1.1],
    "abg_hhb":          [9.3, 3.2, 1.7, 2.7, 2.5, 1.2, 1.4, 1.3],
    "abg_so2":          [90.5, 96.7, 98.2, 97.4, 97.8, 98.6, 98.3, 98.5],
    "abg_tco2":         [25.2, 24.3, 24.0, 23.7, 23.1, 22.8, 22.3, 22.7],
}

# Printed reference intervals, as the source report would show them.
REFERENCE = {
    "bilirubin_total": "0.3 - 1.2", "bilirubin_direct": "< 0.2",
    "bilirubin_indirect": "", "ast": "< 50", "alt": "< 45", "alp": "43 - 115",
    "albumin": "3.5 - 5.2", "globulin": "2.3 - 3.5", "protein_total": "6.4 - 8.3",
    "ag_ratio": "0.9 - 2", "ammonia": "0 - 54",
    "pt": "10.8 - 13.2", "pt_mnpt": "", "inr": "Normal <1.3",
    "platelets": "150 - 410",
    "creatinine": "0.67 - 1.17", "urea": "13 - 43", "sodium": "136 - 145",
    "potassium": "3.5 - 5.1", "chloride": "98 - 107", "calcium": "8.6 - 10.3",
    "magnesium": "1.7 - 2.4", "phosphorus": "2.5 - 4.5",
    "hemoglobin": "13.0 - 17.0", "rbc": "4.5 - 5.5", "pcv": "40.0 - 50.0",
    "mcv": "83.0 - 101.0", "mch": "27.0 - 32.0", "mchc": "31.5 - 34.5",
    "rdw": "11.6 - 14", "mpv": "7.4 - 10.4", "wbc": "4000 - 10000",
    "neutrophils_pct": "40 - 80", "lymphocytes_pct": "20 - 40",
    "monocytes_pct": "2.0 - 10.0", "eosinophils_pct": "1.0 - 6.0",
    "basophils_pct": "0 - 2.0", "anc": "2000 - 7000", "alc": "1000 - 3000",
    "amc": "200 - 1000", "aec": "20 - 500", "abc": "20 - 100", "nlr": "",
    "procalcitonin": "< 0.5", "crp": "< 10", "il6": "< 7.0",
    "abg_ph": "7.350 - 7.450", "abg_pco2": "35 - 45", "abg_po2": "80 - 100",
    "abg_hco3": "", "abg_be": "< 1.000", "lactate": "0.500 - 2.200",
    "abg_sodium": "135 - 145", "abg_potassium": "3.500 - 5.300",
    "abg_chloride": "98 - 106", "abg_calcium": "4.010 - 5.290",
    "abg_hct": "41 - 51", "abg_glucose": "70 - 110", "abg_thb": "13.500 - 18",
    "abg_o2hb": "94 - 97", "abg_cohb": "1.500 - 5", "abg_methb": "0.400 - 1.500",
    "abg_hhb": "0 - 5", "abg_so2": "", "abg_tco2": "23 - 29",
}

CRITICAL = {("ammonia", 5), ("bilirubin_total", 6), ("abg_po2", 0), ("phosphorus", 2)}


def build() -> dict:
    days = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]
    observations = []
    page = 0

    for analyte, values in SERIES.items():
        if analyte not in C.ANALYTES:
            continue
        meta = C.ANALYTES[analyte]
        for i, value in enumerate(values):
            if value is None:
                continue
            page += 1
            collected = f"{days[i]}T{7 + (i % 3) * 4:02d}:{15 + (i * 7) % 40:02d}"
            ref_text = REFERENCE.get(analyte, "")
            ref = validate.parse_reference(ref_text)
            interp = validate.interpret(value, ref)
            crit = (analyte, i) in CRITICAL
            if crit and interp in ("H", "L"):
                interp = "HH" if interp == "H" else "LL"

            observations.append({
                "analyte": analyte, "display": meta["display"],
                "sample_id": f"SYN{100000 + page}", "collected": collected,
                "day": i + 1, "kind": "quantity",
                "value": value, "text": None, "unit": meta["unit"],
                "reference": ref, "reference_text": ref_text,
                "interpretation": interp,
                "printed_flag": {"HH": "CH", "LL": "CL"}.get(interp, interp),
                "critical": interp in ("HH", "LL"),
                "needs_review": False,
                "page": page,
                "provenance": {
                    "page": page, "bbox": None, "crop": None,
                    "ocr": {"A": value, "B": value, "C": value},
                    "gates": {
                        "ensemble": {"state": "pass", "detail": "synthetic"},
                        "envelope": {"state": "pass", "detail": "synthetic"},
                        "flag_consistency": {"state": "pass", "detail": "synthetic"},
                    },
                    "human_verified": True,
                    "synthetic": True,
                },
            })

    # Scores and patterns come from the real code paths, so the demo exercises
    # the same logic the pipeline uses rather than a parallel fake.
    from src.build import (build_analytics, build_formula_cards, build_glossary,
                           build_multivariate)

    by_day = {}
    for o in observations:
        by_day.setdefault(o["collected"][:10], {})[o["analyte"]] = o["value"]

    score_rows = []
    carried: dict[str, float] = {}
    for i, day in enumerate(days):
        vals = dict(carried)
        vals.update(by_day.get(day, {}))
        carried.update(by_day.get(day, {}))
        score_rows.append({
            "collected": f"{day}T12:00", "date": day, "day": i + 1,
            "carried_forward": {},
            "meld3": dict(scores.meld3(
                bilirubin=vals.get("bilirubin_total"), inr=vals.get("inr"),
                creatinine=vals.get("creatinine"), sodium=vals.get("sodium"),
                albumin=vals.get("albumin"), female=False, dialysis=False),
                assumptions=["no renal replacement therapy (synthetic case)"]),
            "meld_na": scores.meld_na(
                bilirubin=vals.get("bilirubin_total"), inr=vals.get("inr"),
                creatinine=vals.get("creatinine"), sodium=vals.get("sodium")),
            "child_pugh": scores.child_pugh(
                bilirubin=vals.get("bilirubin_total"), albumin=vals.get("albumin"),
                inr=vals.get("inr"), ascites=None, encephalopathy=None),
            "aarc": scores.aarc(
                bilirubin=vals.get("bilirubin_total"), creatinine=vals.get("creatinine"),
                inr=vals.get("inr"), lactate=vals.get("lactate"), encephalopathy=None),
        })

    found = patterns.find_patterns(observations, scores=score_rows)
    mv = build_multivariate(observations, days)

    return {
        "patient": {"sex": "male", "synthetic": True},
        "generated_from": {"pages": page, "source": "synthetic"},
        "synthetic": True,
        "days": days,
        "samples": [],
        "observations": observations,
        "scores": score_rows,
        "formulas": build_formula_cards(score_rows[-1] if score_rows else {}),
        "glossary": build_glossary(observations),
        "multivariate": mv,
        "analytics": build_analytics(observations, days, mv),
        "patterns": found,
        "coverage": {"pages": page, "observations": len(observations),
                     "pages_with_no_observations": []},
    }


def main(argv: list[str]) -> int:
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else C.LABS_JSON
    data = build()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")

    print(f"written      : {out}")
    print(f"observations : {len(data['observations'])}")
    print(f"days         : {data['days'][0]} to {data['days'][-1]}")
    print(f"patterns     : {len(data['patterns'])}")
    meld = [r["meld_na"]["value"] for r in data["scores"]]
    print(f"MELD-Na      : {meld}")
    print("\nEvery value above is invented. No real measurement was transformed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
