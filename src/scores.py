"""Clinical severity scores, as pure arithmetic.

Owns: MELD 3.0, MELD-Na, Child-Pugh, AARC, and three small derived quantities
(NLR, anion gap, Maddrey DF). Every function takes plain numbers and returns the
same shape:

    {"value": float|int|None, "complete": bool, "missing": [str],
     "inputs": {...}, "band": str, "notes": [str]}

`notes` carries caveats about the inputs themselves (AARC's blood-gas lactate,
below); it is always present and usually empty.

Does NOT own: reading labs.json, choosing which day's values to feed in, unit
conversion, or any rendering. It never touches a file and never imports anything
but math and config. Feed it the wrong units and it will happily compute
nonsense -- unit checking belongs to the parser.

Two rules this file exists to enforce (docs/DECISIONS.md D9):

  1. A missing CLINICAL input is never defaulted. Ascites and encephalopathy are
     bedside findings; assuming "none" because the field is blank computes a
     reassuring score for a patient who may be encephalopathic. Missing input ->
     complete=False, value=None, and the input named in `missing`.
  2. No coefficient is written from memory. MELD 3.0 and MELD-Na are transcribed
     from the sources in docs/RESEARCH.md; everything else carries its source in
     FORMULA_DOCS at the foot of this file.

Units, and they are not interchangeable: bilirubin mg/dL, creatinine mg/dL,
albumin g/dL, sodium mEq/L (SERUM sodium -- never the abg_sodium key, see
docs/SCHEMA.md), lactate mmol/L, PT seconds.
"""

from __future__ import annotations

import math

from . import config as C

# Vocabulary for the two clinical inputs. Free text is rejected rather than
# guessed at: a typo that silently scored as "none" is the failure mode D9 is
# about.
ASCITES = ("none", "mild", "moderate")          # mild = diuretic-controlled
ENCEPHALOPATHY = ("none", "grade1-2", "grade3-4")

# AARC cut-points below are transcribed from the APASL source in
# docs/RESEARCH.md (Hep Int 10.1007/s12072-017-9816-z, cut-points via
# PMC8579631). Confirm them against the unit's own reference card before any
# clinical use -- consortium scores get re-derived, and a stale cut-point moves
# a grade boundary without moving a number anyone would notice.

# config.ANALYTES["lactate"] is group="abg": the only lactate this dataset has
# is the blood-gas one. Dropping the item would make every AARC incomplete, and
# quietly feeding it in would pass a bedside cartridge value off as the serum
# assay the score was derived on. So it is used, and every AARC says so.
LACTATE_NOTE = "computed with blood-gas lactate (Lac), not a serum assay"


def _round_half_up(x: float) -> int:
    """Round .5 away from zero. Python's round() is banker's rounding, which
    turns a 30.5 into 30 and disagrees with every published calculator."""
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


def _result(value, inputs: dict, missing=(), band: str = "", notes=()) -> dict:
    """The one return shape. An incomplete score has no value and no band --
    a partial number is worse than no number, because it gets read as a number.

    `notes` survives incompleteness: a caveat about which specimen an input came
    from is true whether or not the score computed."""
    missing = list(missing)
    complete = not missing
    return {
        "value": value if complete else None,
        "complete": complete,
        "missing": missing,
        "inputs": inputs,
        "band": band if complete else "",
        "notes": list(notes),
    }


def _absent(inputs: dict) -> list[str]:
    return [k for k, v in inputs.items() if v is None]


def _points(value: float, lo_cut: float, hi_cut: float) -> int:
    """1/2/3 points: below lo_cut, between (inclusive), above hi_cut.

    Every ordinal item in Child-Pugh and AARC has this shape, so the boundary
    convention is decided once here instead of eleven times below.
    """
    if value < lo_cut:
        return 1
    if value <= hi_cut:
        return 2
    return 3


# MELD has no official class system, so these bins are presentational only --
# score ranges with no mortality figure attached, because this module will not
# state a survival percentage it cannot cite (docs/RESEARCH.md).
def _meld_band(v: int) -> str:
    for hi, label in ((9, "<=9"), (19, "10-19"), (29, "20-29"), (39, "30-39")):
        if v <= hi:
            return label
    return ">=40"


def _meld_final(raw: float) -> int:
    """Round half-up, then hold the published [6,40] reporting range.

    Both MELD variants end this way, so the range constants live in one place.
    With the input clamps in force the raw score cannot actually fall below 6 --
    the floor is a guard against a mis-transcribed coefficient, which is exactly
    why it is tested here rather than through the scoring functions."""
    return int(_clamp(_round_half_up(raw), 6, 40))


def meld3(bilirubin=None, inr=None, creatinine=None, sodium=None, albumin=None,
          female: bool | None = False, dialysis: bool | None = False) -> dict:
    """MELD 3.0.

    Formula: 1.33*female + 4.56*ln(bili) + 0.82*(137-Na) - 0.24*(137-Na)*ln(bili)
             + 9.09*ln(INR) + 11.14*ln(Cr) + 1.85*(3.5-alb)
             - 1.83*(3.5-alb)*ln(Cr) + 6
    Clamps applied first: bili>=1, INR>=1, Cr in [1,3], Na in [125,137],
    alb in [1.5,3.5]; Cr is set to 3.0 outright when the patient was dialysed
    (>=2 sessions or 24h of CVVHD in the prior week). Result rounded, then
    clamped to [6,40].

    female and dialysis are tri-state: True, False, or None for "not recorded".
    None is missing, never False -- sex is a required MELD 3.0 input, and a
    dialysed patient's creatinine is a treated number, not a renal one.

    Plain: A single number from five blood tests that says how badly the liver
    is failing; higher is worse, and it is the number transplant waiting lists
    are ordered by.
    Clinical: MELD 3.0 (2023 OPTN revision) adds albumin and sex to MELD-Na and
    re-fits the bilirubin/sodium and albumin/creatinine interaction terms.
    """
    inputs = {"bilirubin_total": bilirubin, "inr": inr, "creatinine": creatinine,
              "sodium": sodium, "albumin": albumin, "female": female,
              "dialysis": dialysis}
    missing = _absent(inputs)
    if missing:
        return _result(None, inputs, missing)
    inputs["female"], inputs["dialysis"] = bool(female), bool(dialysis)

    bili = max(bilirubin, 1.0)
    inr_ = max(inr, 1.0)
    # Dialysis replaces the measured creatinine rather than clamping it: the
    # machine, not the kidney, is holding it down, so the low number is an
    # artefact of treatment and would score the patient as less ill.
    cr = 3.0 if dialysis else _clamp(creatinine, 1.0, 3.0)
    na = _clamp(sodium, 125.0, 137.0)
    alb = _clamp(albumin, 1.5, 3.5)

    ln_b, ln_c = math.log(bili), math.log(cr)
    raw = (1.33 * (1 if female else 0)
           + 4.56 * ln_b
           + 0.82 * (137 - na)
           - 0.24 * (137 - na) * ln_b
           + 9.09 * math.log(inr_)
           + 11.14 * ln_c
           + 1.85 * (3.5 - alb)
           - 1.83 * (3.5 - alb) * ln_c
           + 6)
    value = _meld_final(raw)
    return _result(value, inputs, band=_meld_band(value))


def meld_na(bilirubin=None, inr=None, creatinine=None, sodium=None,
            dialysis: bool | None = False) -> dict:
    """MELD-Na (UNOS).

    Formula: MELD(i) = round(10*(0.957*ln(Cr) + 0.378*ln(bili)
                                 + 1.120*ln(INR) + 0.643), 1); if MELD(i) > 11:
             MELD-Na = MELD(i) + 1.32*(137-Na) - 0.033*MELD(i)*(137-Na)
    Clamps: bili/INR/Cr >= 1.0, Cr capped at 4.0 (and set to 4.0 when the
    patient had dialysis twice in the past week), Na in [125,137]. Rounded and
    clamped to [6,40]. dialysis=None means not recorded, and is missing.

    Plain: The older version of the same score, still the one most hospitals
    quote; it uses three blood tests plus the salt level in blood.
    Clinical: The sodium correction applies only above MELD(i) 11, which is why
    a low MELD is unchanged by hyponatraemia.
    """
    inputs = {"bilirubin_total": bilirubin, "inr": inr, "creatinine": creatinine,
              "sodium": sodium, "dialysis": dialysis}
    missing = _absent(inputs)
    if missing:
        return _result(None, inputs, missing)
    inputs["dialysis"] = bool(dialysis)

    bili = max(bilirubin, 1.0)
    inr_ = max(inr, 1.0)
    cr = 4.0 if dialysis else _clamp(creatinine, 1.0, 4.0)

    # The x10 rounding to one decimal happens BEFORE the sodium term: the
    # policy's MELD(i) is the rounded value, and it appears twice in the
    # correction, so rounding late shifts the result.
    meld_i = round(10 * (0.957 * math.log(cr)
                         + 0.378 * math.log(bili)
                         + 1.120 * math.log(inr_)
                         + 0.643), 1)
    score = meld_i
    if meld_i > 11:
        na = _clamp(sodium, 125.0, 137.0)
        score = meld_i + 1.32 * (137 - na) - 0.033 * meld_i * (137 - na)

    value = _meld_final(score)
    return _result(value, inputs, band=_meld_band(value))


def child_pugh(bilirubin=None, albumin=None, inr=None,
               ascites=None, encephalopathy=None) -> dict:
    """Child-Turcotte-Pugh.

    Formula: 1/2/3 points each for bilirubin (<2 / 2-3 / >3 mg/dL), albumin
             (>3.5 / 2.8-3.5 / <2.8 g/dL), INR (<1.7 / 1.7-2.3 / >2.3), ascites
             (none / mild / moderate), encephalopathy (none / grade I-II /
             grade III-IV). Total 5-15; class A 5-6, B 7-9, C 10-15.

    Plain: A grade from A to C that mixes three blood tests with two things the
    doctor has to look for at the bedside: fluid in the belly and confusion.
    Clinical: Ascites and encephalopathy are not in the lab data, so this
    returns incomplete rather than assuming they are absent.
    """
    inputs = {"bilirubin_total": bilirubin, "albumin": albumin, "inr": inr,
              "ascites_grade": ascites, "encephalopathy_grade": encephalopathy}
    missing = _absent(inputs)
    if missing:
        return _result(None, inputs, missing)
    if ascites not in ASCITES:
        raise ValueError(f"ascites must be one of {ASCITES}, got {ascites!r}")
    if encephalopathy not in ENCEPHALOPATHY:
        raise ValueError(f"encephalopathy must be one of {ENCEPHALOPATHY}, "
                         f"got {encephalopathy!r}")

    # Albumin scores in the opposite direction to the others: high is good.
    alb_pts = 1 if albumin > 3.5 else (3 if albumin < 2.8 else 2)
    total = (_points(bilirubin, 2.0, 3.0)
             + alb_pts
             + _points(inr, 1.7, 2.3)
             + ASCITES.index(ascites) + 1
             + ENCEPHALOPATHY.index(encephalopathy) + 1)
    band = "A" if total <= 6 else ("B" if total <= 9 else "C")
    return _result(total, inputs, band=band)


def aarc(bilirubin=None, creatinine=None, inr=None, lactate=None,
         encephalopathy=None) -> dict:
    """AARC (APASL ACLF Research Consortium) score.

    Formula: 1/2/3 points each for bilirubin (<15 / 15-25 / >25 mg/dL),
             creatinine (<0.7 / 0.7-1.5 / >1.5 mg/dL), INR (<1.8 / 1.8-2.5 /
             >2.5), lactate (<1.5 / 1.5-2.5 / >2.5 mmol/L), hepatic
             encephalopathy (none / grade I-II / grade III-IV). Total 5-15;
             grade I 5-7, II 8-10, III 11-15.

    Plain: A grade from I to III used for sudden liver failure, adding two ICU
    measurements -- the acid level in blood and how confused the patient is.
    Clinical: Five equally weighted organ-failure items; the grade tracks the
    number of failing systems rather than the depth of any one of them. AARC
    was derived on serum lactate, but the only lactate in this dataset is the
    blood-gas one, so every result carries a note saying so rather than
    silently substituting one assay for the other.
    """
    inputs = {"bilirubin_total": bilirubin, "creatinine": creatinine, "inr": inr,
              "lactate": lactate, "encephalopathy_grade": encephalopathy}
    missing = _absent(inputs)
    if missing:
        return _result(None, inputs, missing, notes=[LACTATE_NOTE])
    if encephalopathy not in ENCEPHALOPATHY:
        raise ValueError(f"encephalopathy must be one of {ENCEPHALOPATHY}, "
                         f"got {encephalopathy!r}")

    total = (_points(bilirubin, 15.0, 25.0)
             + _points(creatinine, 0.7, 1.5)
             + _points(inr, 1.8, 2.5)
             + _points(lactate, 1.5, 2.5)
             + ENCEPHALOPATHY.index(encephalopathy) + 1)
    band = "I" if total <= 7 else ("II" if total <= 10 else "III")
    return _result(total, inputs, band=band, notes=[LACTATE_NOTE])


def nlr(anc=None, alc=None) -> dict:
    """Neutrophil-to-lymphocyte ratio.

    Formula: ANC / ALC (both absolute counts, same units).

    Plain: Two kinds of infection-fighting cell divided by each other; the ratio
    climbs when the body is fighting hard and losing ground.
    Clinical: The trend carries the information. No cut-point is asserted here
    because none is cited in docs/RESEARCH.md.
    """
    inputs = {"anc": anc, "alc": alc}
    missing = _absent(inputs)
    # A zero lymphocyte count is a real (grave) result, but it makes the ratio
    # undefined -- report it as unusable rather than as infinity.
    if not missing and alc == 0:
        missing = ["alc"]
    if missing:
        return _result(None, inputs, missing)
    return _result(round(anc / alc, 2), inputs)


def anion_gap(abg_sodium=None, abg_chloride=None, abg_hco3=None) -> dict:
    """Anion gap, computed entirely within the blood-gas specimen.

    Formula: abg_sodium - (abg_chloride + abg_hco3), potassium excluded.

    Plain: A check that the salts in blood add up; a wide gap means acid is
    building up somewhere.
    Clinical: bicarbonate exists in this dataset only as abg_hco3, so all three
    terms are taken from the blood gas; mixing a serum sodium and chloride with
    an ABG bicarbonate yields a gap made of two instruments' calibration
    offsets. Used here mainly as an extraction check -- config.ANION_GAP_RANGE
    is a physiological envelope for catching OCR errors, not a reference range.
    """
    inputs = {"abg_sodium": abg_sodium, "abg_chloride": abg_chloride,
              "abg_hco3": abg_hco3}
    missing = _absent(inputs)
    if missing:
        return _result(None, inputs, missing)
    value = round(abg_sodium - (abg_chloride + abg_hco3), 1)
    lo, hi = C.ANION_GAP_RANGE
    return _result(value, inputs,
                   band="in-envelope" if lo <= value <= hi else "outside-envelope")


def maddrey_df(pt_seconds=None, control_pt_seconds=None, bilirubin=None) -> dict:
    """Maddrey discriminant function.

    Formula: 4.6*(PT - control PT) + bilirubin, PT in seconds, bili in mg/dL.
             DF >= 32 is the severe band.

    Plain: A number used when heavy alcohol use is the suspected cause, mixing
    how slowly the blood clots with the yellow pigment level.
    Clinical: Relevant in alcohol-related hepatitis. DF >= 32 defines severe
    alcoholic hepatitis (MDCalc, docs/RESEARCH.md); the control PT must be the
    reporting laboratory's own mean normal PT, since the difference, not either
    number, is what the coefficient multiplies.
    """
    inputs = {"pt": pt_seconds, "pt_mnpt": control_pt_seconds,
              "bilirubin_total": bilirubin}
    missing = _absent(inputs)
    if missing:
        return _result(None, inputs, missing)
    value = round(4.6 * (pt_seconds - control_pt_seconds) + bilirubin, 1)
    return _result(value, inputs, band="severe" if value >= 32 else "non-severe")


# --------------------------------------------------------------------------
# Dashboard-facing copy for the Formulas tab. Same prose AND same equations as
# the docstrings; the test asserts every field appears verbatim in the
# docstring, which is cheaper than generating one from the other and leaves both
# readable where they are read. A coefficient edited here and nowhere else is a
# published formula that no longer describes the code, so "formula" is checked
# character for character like the rest.
# --------------------------------------------------------------------------
FORMULA_DOCS = {
    "meld3": {
        "formula": ("1.33*female + 4.56*ln(bili) + 0.82*(137-Na) "
                    "- 0.24*(137-Na)*ln(bili) + 9.09*ln(INR) + 11.14*ln(Cr) "
                    "+ 1.85*(3.5-alb) - 1.83*(3.5-alb)*ln(Cr) + 6"),
        "plain": ("A single number from five blood tests that says how badly the "
                  "liver is failing; higher is worse, and it is the number "
                  "transplant waiting lists are ordered by."),
        "clinical": ("MELD 3.0 (2023 OPTN revision) adds albumin and sex to MELD-Na "
                     "and re-fits the bilirubin/sodium and albumin/creatinine "
                     "interaction terms."),
        "source": "MDCalc + UW Hepatitis B Online, via docs/RESEARCH.md",
    },
    "meld_na": {
        "formula": ("MELD(i) = round(10*(0.957*ln(Cr) + 0.378*ln(bili) "
                    "+ 1.120*ln(INR) + 0.643), 1); if MELD(i) > 11: MELD-Na = "
                    "MELD(i) + 1.32*(137-Na) - 0.033*MELD(i)*(137-Na)"),
        "plain": ("The older version of the same score, still the one most "
                  "hospitals quote; it uses three blood tests plus the salt level "
                  "in blood."),
        "clinical": ("The sodium correction applies only above MELD(i) 11, which is "
                     "why a low MELD is unchanged by hyponatraemia."),
        "source": "UNOS/OPTN policy, via docs/RESEARCH.md",
    },
    "child_pugh": {
        "formula": ("1/2/3 points each for bilirubin (<2 / 2-3 / >3 mg/dL), albumin "
                    "(>3.5 / 2.8-3.5 / <2.8 g/dL), INR (<1.7 / 1.7-2.3 / >2.3), "
                    "ascites (none / mild / moderate), encephalopathy (none / "
                    "grade I-II / grade III-IV). Total 5-15; class A 5-6, B 7-9, "
                    "C 10-15."),
        "plain": ("A grade from A to C that mixes three blood tests with two things "
                  "the doctor has to look for at the bedside: fluid in the belly "
                  "and confusion."),
        "clinical": ("Ascites and encephalopathy are not in the lab data, so this "
                     "returns incomplete rather than assuming they are absent."),
        "source": "standard Child-Turcotte-Pugh, docs/RESEARCH.md",
    },
    "aarc": {
        "formula": ("1/2/3 points each for bilirubin (<15 / 15-25 / >25 mg/dL), "
                    "creatinine (<0.7 / 0.7-1.5 / >1.5 mg/dL), INR (<1.8 / 1.8-2.5 "
                    "/ >2.5), lactate (<1.5 / 1.5-2.5 / >2.5 mmol/L), hepatic "
                    "encephalopathy (none / grade I-II / grade III-IV). Total 5-15; "
                    "grade I 5-7, II 8-10, III 11-15."),
        "plain": ("A grade from I to III used for sudden liver failure, adding two "
                  "ICU measurements -- the acid level in blood and how confused the "
                  "patient is."),
        "clinical": ("Five equally weighted organ-failure items; the grade tracks "
                     "the number of failing systems rather than the depth of any "
                     "one of them. AARC was derived on serum lactate, but the only "
                     "lactate in this dataset is the blood-gas one, so every result "
                     "carries a note saying so rather than silently substituting "
                     "one assay for the other."),
        "source": ("APASL AARC, Hep Int 10.1007/s12072-017-9816-z; cut-points via "
                   "PMC8579631 (docs/RESEARCH.md). Confirm against the unit's card."),
    },
    "nlr": {
        "formula": "ANC / ALC",
        "plain": ("Two kinds of infection-fighting cell divided by each other; the "
                  "ratio climbs when the body is fighting hard and losing ground."),
        "clinical": ("The trend carries the information. No cut-point is asserted "
                     "here because none is cited in docs/RESEARCH.md."),
        "source": "derived quantity; config.ANALYTES['nlr']",
    },
    "anion_gap": {
        "formula": "abg_sodium - (abg_chloride + abg_hco3)",
        "plain": ("A check that the salts in blood add up; a wide gap means acid is "
                  "building up somewhere."),
        "clinical": ("bicarbonate exists in this dataset only as abg_hco3, so all "
                     "three terms are taken from the blood gas; mixing a serum "
                     "sodium and chloride with an ABG bicarbonate yields a gap made "
                     "of two instruments' calibration offsets. Used here mainly as "
                     "an extraction check -- config.ANION_GAP_RANGE is a "
                     "physiological envelope for catching OCR errors, not a "
                     "reference range."),
        "source": "derived quantity; envelope from config.ANION_GAP_RANGE",
    },
    "maddrey_df": {
        "formula": "4.6*(PT - control PT) + bilirubin",
        "plain": ("A number used when heavy alcohol use is the suspected cause, "
                  "mixing how slowly the blood clots with the yellow pigment level."),
        "clinical": ("Relevant in alcohol-related hepatitis. DF >= 32 defines severe "
                     "alcoholic hepatitis (MDCalc, docs/RESEARCH.md); the control PT "
                     "must be the reporting laboratory's own mean normal PT, since "
                     "the difference, not either number, is what the coefficient "
                     "multiplies."),
        "source": "Maddrey discriminant function; MDCalc, via docs/RESEARCH.md",
    },
}
