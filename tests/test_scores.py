"""Checks on src/scores.py -- the arithmetic, the clamps, and the refusal to
guess a missing clinical input.

Owns: worked examples computed by hand, boundary cases at every class edge, and
the drift guard between each docstring and FORMULA_DOCS.

Does NOT own: anything that reads labs.json or touches the filesystem. These are
pure-number tests and must stay runnable on a machine with no data present.

Run either way:  python -m tests.test_scores   |   pytest tests/test_scores.py
"""

from src import config as C
from src import scores as S


def test_meld3_worked_example():
    """Bili 8.1, INR 3.18, Cr 1.2, Na 130, alb 2.4, male. Arithmetic by hand:

        ln(8.1) = 2.0918641   ln(2.89) = 1.0612565   ln(1.2) = 0.1823216
        4.56*ln(bili)                =  9.5389001
        0.82*(137-130) = 0.82*7      =  5.7400000
       -0.24*7*ln(bili) = -1.68*...  = -3.5143316
        9.09*ln(INR)                 =  9.6468217
       11.14*ln(Cr)                  =  2.0310622
        1.85*(3.5-2.4) = 1.85*1.1    =  2.0350000
       -1.83*1.1*ln(Cr) = -2.013*... = -0.3670133
        + 6                          =  6.0000000
                                       ----------
                                sum  = 31.1104391  -> round -> 31
    """
    r = S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=2.4)
    assert r["complete"] is True, r
    assert r["missing"] == []
    assert r["value"] == 31, r
    assert r["band"] == "30-39", r
    assert r["inputs"]["sodium"] == 130


def test_meld3_clamps():
    # bilirubin below 1.0 is treated as 1.0 ...
    low = S.meld3(bilirubin=0.4, inr=1.5, creatinine=1.5, sodium=134, albumin=3.0)
    at1 = S.meld3(bilirubin=1.0, inr=1.5, creatinine=1.5, sodium=134, albumin=3.0)
    assert low["value"] == at1["value"], (low, at1)

    # ... creatinine above 3.0 is treated as 3.0 ...
    high = S.meld3(bilirubin=8.1, inr=2.89, creatinine=6.0, sodium=130, albumin=2.4)
    at3 = S.meld3(bilirubin=8.1, inr=2.89, creatinine=3.0, sodium=130, albumin=2.4)
    assert high["value"] == at3["value"], (high, at3)

    # ... sodium below 125 and albumin outside [1.5, 3.5] likewise.
    assert (S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=118, albumin=2.4)["value"]
            == S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=125, albumin=2.4)["value"])
    assert (S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=1.0)["value"]
            == S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=1.5)["value"])

    # A healthy set floors at 6, never below.
    assert S.meld3(bilirubin=0.6, inr=1.0, creatinine=0.8,
                   sodium=140, albumin=4.2)["value"] == 6


def test_meld_reporting_range_is_held_at_both_ends():
    """Every input clamp is one-sided upward, so no combination of numbers can
    drive a raw MELD below 6 -- the floor is only reachable if a coefficient is
    mis-transcribed. Test it where it lives instead of pretending otherwise:
    a raw 3.2 must still report 6, not 3."""
    assert S._meld_final(3.2) == 6
    assert S._meld_final(-4.0) == 6
    assert S._meld_final(5.9) == 6
    assert S._meld_final(6.4) == 6
    assert S._meld_final(55.0) == 40


def test_meld3_dialysis_forces_creatinine_to_3():
    """A dialysed patient's creatinine is what the machine left behind, not what
    the kidney is doing; scoring it raw reads as renal recovery. Same day's
    numbers, Cr 0.9 measured on dialysis."""
    on = S.meld3(bilirubin=8.1, inr=2.89, creatinine=0.9, sodium=130,
                 albumin=2.4, dialysis=True)
    off = S.meld3(bilirubin=8.1, inr=2.89, creatinine=0.9, sodium=130,
                  albumin=2.4)
    at_3 = S.meld3(bilirubin=8.1, inr=2.89, creatinine=3.0, sodium=130,
                   albumin=2.4)
    assert off["value"] == 29, off
    assert on["value"] == 39, on          # ten points of severity, not a rounding
    assert on["value"] == at_3["value"]
    assert on["inputs"]["dialysis"] is True

    # and it is the substitution, not a clamp: a Cr above 3.0 lands in the same
    # place whether or not dialysis is recorded
    assert (S.meld3(bilirubin=8.1, inr=2.89, creatinine=6.0, sodium=130,
                    albumin=2.4, dialysis=True)["value"] == at_3["value"])


def test_unknown_sex_or_dialysis_is_missing_not_false():
    """None means "not recorded". Coercing it to False scores an unknown sex as
    male -- a whole 1.33 points -- and it can never surface in `missing`."""
    labs = dict(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=2.4)

    unknown_sex = S.meld3(female=None, **labs)
    assert unknown_sex["complete"] is False, unknown_sex
    assert unknown_sex["value"] is None
    assert unknown_sex["missing"] == ["female"]
    assert unknown_sex["inputs"]["female"] is None

    unknown_rrt = S.meld3(dialysis=None, **labs)
    assert unknown_rrt["missing"] == ["dialysis"], unknown_rrt
    assert unknown_rrt["value"] is None

    na = S.meld_na(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130,
                   dialysis=None)
    assert na["missing"] == ["dialysis"] and na["value"] is None, na

    # a recorded False still scores, and still reads back as a bool
    known = S.meld3(female=False, **labs)
    assert known["value"] == 31 and known["inputs"]["female"] is False


def test_meld3_female_adds_1_33():
    male = S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=2.4)
    female = S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=2.4,
                     female=True)
    # 31.110 + 1.33 = 32.440 -> 32
    assert male["value"] == 31 and female["value"] == 32


def test_meld3_missing_input():
    r = S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=None, albumin=2.4)
    assert r["complete"] is False
    assert r["value"] is None
    assert r["band"] == ""
    assert r["missing"] == ["sodium"]


def test_meld_na_worked_example():
    """Same day's numbers, bili 8.1, INR 3.18, Cr 1.2, Na 130:

        0.957*ln(1.2) = 0.1744817
        0.378*ln(8.1) = 0.7907246
        1.120*ln(2.89)= 1.1886073
        + 0.643                     -> 2.7968136  x10 = 27.968 -> 28.0
        28.0 > 11, so
        28.0 + 1.32*7 - 0.033*28.0*7 = 28.0 + 9.24 - 6.468 = 30.772 -> 31
    """
    r = S.meld_na(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130)
    assert r["complete"] is True
    assert r["value"] == 31, r


def test_meld_na_sodium_term_only_above_11():
    """Below MELD(i) 11 the sodium term must not fire, however low the sodium."""
    mild = dict(bilirubin=1.0, inr=1.0, creatinine=1.0)
    assert (S.meld_na(sodium=137, **mild)["value"]
            == S.meld_na(sodium=125, **mild)["value"] == 6)


def test_meld_na_dialysis_forces_creatinine_to_4():
    on_dialysis = S.meld_na(bilirubin=8.1, inr=2.89, creatinine=0.9, sodium=130,
                            dialysis=True)
    at_4 = S.meld_na(bilirubin=8.1, inr=2.89, creatinine=4.0, sodium=130)
    assert on_dialysis["value"] == at_4["value"]
    # and creatinine is capped at 4.0, not 3.0 as in MELD 3.0
    assert (S.meld_na(bilirubin=8.1, inr=2.89, creatinine=9.0, sodium=130)["value"]
            == at_4["value"])


def test_child_pugh_incomplete_without_clinical_inputs():
    r = S.child_pugh(bilirubin=8.1, albumin=2.4, inr=2.89)
    assert r["complete"] is False
    assert r["value"] is None
    assert r["missing"] == ["ascites_grade", "encephalopathy_grade"]

    r = S.child_pugh(bilirubin=8.1, albumin=2.4, inr=2.89, ascites="none")
    assert r["missing"] == ["encephalopathy_grade"]


def test_child_pugh_class_boundaries():
    # 6 points -> A: bili 2.5 (2) + alb 3.6 (1) + INR 1.2 (1) + none (1) + none (1)
    six = S.child_pugh(bilirubin=2.5, albumin=3.6, inr=1.2,
                       ascites="none", encephalopathy="none")
    assert (six["value"], six["band"]) == (6, "A"), six

    # 7 points -> B: drop albumin into the 2.8-3.5 band
    seven = S.child_pugh(bilirubin=2.5, albumin=3.0, inr=1.2,
                         ascites="none", encephalopathy="none")
    assert (seven["value"], seven["band"]) == (7, "B"), seven

    # 9 points -> B: 2+2+2+2+1
    nine = S.child_pugh(bilirubin=2.5, albumin=3.0, inr=2.0,
                        ascites="mild", encephalopathy="none")
    assert (nine["value"], nine["band"]) == (9, "B"), nine

    # 10 points -> C: encephalopathy grade I-II adds the tenth point
    ten = S.child_pugh(bilirubin=2.5, albumin=3.0, inr=2.0,
                       ascites="mild", encephalopathy="grade1-2")
    assert (ten["value"], ten["band"]) == (10, "C"), ten

    # 15 is the ceiling
    worst = S.child_pugh(bilirubin=8.1, albumin=2.4, inr=2.89,
                         ascites="moderate", encephalopathy="grade3-4")
    assert (worst["value"], worst["band"]) == (15, "C"), worst


def test_child_pugh_item_boundaries_are_inclusive():
    """bili exactly 2.0 and 3.0 both score 2; INR 1.7 and 2.3 both score 2;
    albumin exactly 3.5 scores 2 and exactly 2.8 scores 2."""
    base = dict(ascites="none", encephalopathy="none")
    assert S.child_pugh(bilirubin=2.0, albumin=4.0, inr=1.0, **base)["value"] == 5 + 1
    assert S.child_pugh(bilirubin=3.0, albumin=4.0, inr=1.0, **base)["value"] == 6
    assert S.child_pugh(bilirubin=3.01, albumin=4.0, inr=1.0, **base)["value"] == 7
    assert S.child_pugh(bilirubin=1.0, albumin=3.5, inr=1.0, **base)["value"] == 6
    assert S.child_pugh(bilirubin=1.0, albumin=2.8, inr=1.0, **base)["value"] == 6
    assert S.child_pugh(bilirubin=1.0, albumin=2.79, inr=1.0, **base)["value"] == 7
    assert S.child_pugh(bilirubin=1.0, albumin=4.0, inr=1.7, **base)["value"] == 6
    assert S.child_pugh(bilirubin=1.0, albumin=4.0, inr=2.3, **base)["value"] == 6
    assert S.child_pugh(bilirubin=1.0, albumin=4.0, inr=2.31, **base)["value"] == 7


def test_child_pugh_rejects_unknown_grade():
    try:
        S.child_pugh(bilirubin=1.0, albumin=4.0, inr=1.0,
                     ascites="tense", encephalopathy="none")
    except ValueError as e:
        assert "ascites" in str(e)
    else:
        raise AssertionError("an unrecognised ascites grade must not be scored")


def test_aarc_incomplete_without_encephalopathy():
    r = S.aarc(bilirubin=8.1, creatinine=1.2, inr=2.89, lactate=2.0)
    assert r["complete"] is False
    assert r["value"] is None
    assert r["missing"] == ["encephalopathy_grade"]

    # lactate comes from the ABG, and is missing on days with no gas
    r = S.aarc(bilirubin=8.1, creatinine=1.2, inr=2.89, encephalopathy="none")
    assert r["missing"] == ["lactate"]


def test_aarc_grade_boundaries():
    # 5 points -> grade I: bili 8.1 (1) + Cr 0.6 (1) + INR 1.5 (1) + lac 1.0 (1) + none (1)
    g1 = S.aarc(bilirubin=8.1, creatinine=0.6, inr=1.5, lactate=1.0,
                encephalopathy="none")
    assert (g1["value"], g1["band"]) == (5, "I"), g1

    # 8 points -> grade II: 1 + 2 (Cr 1.2) + 2 (INR 2.0) + 2 (lac 2.0) + 1
    g2 = S.aarc(bilirubin=8.1, creatinine=1.2, inr=2.0, lactate=2.0,
                encephalopathy="none")
    assert (g2["value"], g2["band"]) == (8, "II"), g2

    # 11 points -> grade III: 2 (bili 20) + 2 + 3 (INR 3.18) + 2 + 2
    g3 = S.aarc(bilirubin=20.0, creatinine=1.2, inr=2.89, lactate=2.0,
                encephalopathy="grade1-2")
    assert (g3["value"], g3["band"]) == (11, "III"), g3


def test_aarc_labels_the_blood_gas_lactate():
    """AARC was derived on serum lactate; the only lactate here is off the gas
    machine. Using it silently passes one assay off as another, so the caveat
    rides on the result -- including when the score could not be computed."""
    scored = S.aarc(bilirubin=8.1, creatinine=1.2, inr=2.0, lactate=2.0,
                    encephalopathy="none")
    assert scored["notes"] == [S.LACTATE_NOTE], scored
    assert "blood-gas lactate" in S.LACTATE_NOTE
    assert "not a serum assay" in S.LACTATE_NOTE

    incomplete = S.aarc(bilirubin=8.1, creatinine=1.2, inr=2.0, lactate=2.0)
    assert incomplete["complete"] is False
    assert incomplete["notes"] == [S.LACTATE_NOTE], incomplete

    # every other score keeps the same shape, with nothing to say
    assert S.meld_na(bilirubin=8.1, inr=2.89, creatinine=1.2,
                     sodium=130)["notes"] == []


def test_p40_real_numbers():
    """Page 40, verified by hand in docs/DECISIONS.md D8: PT 38.2 s, mean normal
    PT 12.0 s, INR 3.18 (38.2 / 12.0 = 3.183).

    Maddrey DF = 4.6*(34.3 - 12.0) + 8.1 = 4.6*22.3 + 8.1 = 102.58 + 8.1 = 110.68
    """
    df = S.maddrey_df(pt_seconds=34.3, control_pt_seconds=12.0, bilirubin=8.1)
    assert df["complete"] is True
    assert df["value"] == 110.7, df          # rounded to one decimal
    assert df["band"] == "severe", df        # DF >= 32 (MDCalc, docs/RESEARCH.md)
    assert df["inputs"]["pt"] == 34.3

    # the same day's INR flows into both MELD variants without disagreement
    m3 = S.meld3(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130, albumin=2.4)
    mna = S.meld_na(bilirubin=8.1, inr=2.89, creatinine=1.2, sodium=130)
    assert m3["value"] == 31 and mna["value"] == 31

    assert S.maddrey_df(pt_seconds=34.3, control_pt_seconds=None,
                        bilirubin=8.1)["missing"] == ["pt_mnpt"]


def test_maddrey_band_at_the_cut_point():
    """DF >= 32 is severe alcoholic hepatitis (MDCalc, docs/RESEARCH.md). The
    boundary is inclusive: exactly 32 is severe."""
    # 4.6*(18.0 - 12.0) + 4.4 = 27.6 + 4.4 = 32.0
    at = S.maddrey_df(pt_seconds=18.0, control_pt_seconds=12.0, bilirubin=4.4)
    assert (at["value"], at["band"]) == (32.0, "severe"), at
    # 4.6*6 + 4.3 = 31.9
    below = S.maddrey_df(pt_seconds=18.0, control_pt_seconds=12.0, bilirubin=4.3)
    assert (below["value"], below["band"]) == (31.9, "non-severe"), below


def test_nlr_and_anion_gap():
    assert S.nlr(anc=9000, alc=1200)["value"] == 7.5
    assert S.nlr(anc=9000, alc=None)["missing"] == ["alc"]
    # zero lymphocytes: real result, undefined ratio
    zero = S.nlr(anc=9000, alc=0)
    assert zero["complete"] is False and zero["missing"] == ["alc"]

    gap = S.anion_gap(abg_sodium=130, abg_chloride=98, abg_hco3=18)
    assert gap["value"] == 14.0 and gap["band"] == "in-envelope", gap
    wide = S.anion_gap(abg_sodium=130, abg_chloride=80, abg_hco3=8)
    assert wide["value"] == 42.0 and wide["band"] == "outside-envelope", wide


def test_anion_gap_stays_inside_the_blood_gas_specimen():
    """Bicarbonate exists in this dataset only as abg_hco3. A gap built from a
    serum sodium and an ABG bicarbonate is two instruments' calibration offsets
    subtracted from each other, so the parameter names have to say which
    specimen they mean and the inputs have to name real ABG analytes."""
    assert set(S.anion_gap()["inputs"]) == {"abg_sodium", "abg_chloride",
                                            "abg_hco3"}
    assert S.anion_gap(abg_sodium=130, abg_chloride=98)["missing"] == ["abg_hco3"]
    # "bicarbonate" is not an analyte key; abg_hco3 is, and it is in the ABG group
    assert "bicarbonate" not in C.ANALYTES
    assert C.ANALYTES["abg_hco3"]["group"] == "abg"
    for key in ("abg_sodium", "abg_chloride", "abg_hco3"):
        assert C.ANALYTES[key]["group"] == "abg", key


def test_every_score_input_names_a_real_field():
    """`inputs` is what the dashboard joins back to the measured values, so a
    key that is not an analyte joins to nothing and quietly reports a value the
    patient never had. Only the two bedside findings and the two patient facts
    are allowed to sit outside config.ANALYTES."""
    NOT_ANALYTES = {"ascites_grade", "encephalopathy_grade", "female", "dialysis"}
    calls = {
        "meld3": S.meld3(), "meld_na": S.meld_na(), "child_pugh": S.child_pugh(),
        "aarc": S.aarc(), "nlr": S.nlr(), "anion_gap": S.anion_gap(),
        "maddrey_df": S.maddrey_df(),
    }
    assert set(calls) == set(S.FORMULA_DOCS), "a score was added without a case"
    for name, r in calls.items():
        for key in r["inputs"]:
            assert key in C.ANALYTES or key in NOT_ANALYTES, f"{name}: {key}"


def test_formula_docs_match_docstrings():
    """The Formulas tab reads FORMULA_DOCS; a reader of the source reads the
    docstring. Neither is allowed to drift from the other -- and that includes
    the equation, which is the field a reader is least able to sanity-check and
    the only one where a single wrong digit is a wrong clinical number."""
    def squash(s):
        return " ".join(s.split())

    for name, doc in S.FORMULA_DOCS.items():
        fn = getattr(S, name)
        body = squash(fn.__doc__ or "")
        assert set(doc) == {"formula", "plain", "clinical", "source"}, name
        assert squash(doc["formula"]) in body, f"{name}: formula drifted"
        assert squash(doc["plain"]) in body, f"{name}: plain text drifted"
        assert squash(doc["clinical"]) in body, f"{name}: clinical text drifted"
        assert doc["source"], name

    scored = {"meld3", "meld_na", "child_pugh", "aarc", "nlr", "anion_gap",
              "maddrey_df"}
    assert scored == set(S.FORMULA_DOCS), "every public score needs an entry"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all scores tests pass")
