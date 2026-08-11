"""Tests for the pattern engine.

Owns: proof that each rule fires on the shape it is meant to catch and stays
silent otherwise. The two that earn their keep are `test_flat_abnormal_is_silent`
(this patient is abnormal everywhere; stable is not worsening) and
`test_recovery_reads_as_improvement` (a family reading the tab must be told when
a number turns around).

Does NOT own: any real patient value. Every number here is synthetic and chosen
to sit on the correct side of a threshold, not to look clinical.

Run: `python -m tests.test_patterns` from the repo root, or via pytest.
"""

from src import patterns as P


def obs(analyte, day, value, low=None, high=None, unit="", flag=None, display=None):
    return {
        "analyte": analyte, "display": display or analyte, "sample_id": f"S{day}",
        "collected": f"2026-08-{3 + day:02d}T08:00", "day": day, "kind": "quantity",
        "value": value, "text": None, "unit": unit,
        "reference": {"low": low, "high": high, "text": None},
        "interpretation": None, "printed_flag": flag,
        "provenance": {"human_verified": True},
    }


def series(analyte, values, low=None, high=None, unit="", start_day=1):
    return [obs(analyte, start_day + i, v, low, high, unit)
            for i, v in enumerate(values)]


def ids(patterns):
    return [p["id"] for p in patterns]


def by_id(patterns, id_, analyte=None):
    return [p for p in patterns
            if p["id"] == id_ and (analyte is None or p["analyte"] == analyte)]


# -- rule 1: monotonic runs -------------------------------------------------
def test_rising_run_fires_on_worsening_analyte():
    found = P.find_patterns(series("bilirubin_total", [3.1, 4.8, 6.6, 8.1],
                                   low=0.3, high=1.2, unit="mg/dL"))
    run = by_id(found, "rising-run", "bilirubin_total")
    assert len(run) == 1, ids(found)
    assert run[0]["severity"] == "moderate"        # 4 samples: real, not critical
    assert run[0]["audience"] == ["doctor", "family"]
    assert "8.1" in run[0]["detail"] and "mg/dL" in run[0]["detail"]
    assert [e["value"] for e in run[0]["evidence"]] == [3.1, 4.8, 6.6, 8.1]
    assert not by_id(found, "falling-run")
    # No lab flag anywhere in the input, so nothing may claim critical.
    assert all(p["severity"] != "critical" for p in found)


def test_longer_run_escalates_to_high():
    found = P.find_patterns(series("bilirubin_total", [3.1, 4.0, 5.0, 6.2, 7.5],
                                   low=0.3, high=1.2, unit="mg/dL"))
    assert by_id(found, "rising-run")[0]["severity"] == "high"


def test_two_samples_are_not_a_run():
    found = P.find_patterns(series("bilirubin_total", [3.1, 4.0], low=0.3, high=1.2))
    assert not by_id(found, "rising-run")


def test_flat_abnormal_is_silent():
    """Persistently low albumin is abnormal on every day and worsening on none."""
    found = P.find_patterns(series("albumin", [2.1, 2.1, 2.1, 2.1, 2.1],
                                   low=3.5, high=5.2, unit="g/dL"))
    assert found == [], ids(found)


def test_jitter_is_not_a_trend():
    """Within-noise drift must not be dressed up as a four-day decline."""
    found = P.find_patterns(series("albumin", [2.10, 2.09, 2.08, 2.07],
                                   low=3.5, high=5.2, unit="g/dL"))
    assert not by_id(found, "falling-run"), ids(found)


def test_recovery_reads_as_improvement():
    found = P.find_patterns(series("bilirubin_total", [8.1, 6.6, 4.8, 3.1],
                                   low=0.3, high=1.2, unit="mg/dL"))
    run = by_id(found, "falling-run", "bilirubin_total")
    assert len(run) == 1
    assert run[0]["severity"] == "info"
    assert "right direction" in run[0]["headline"]
    assert "family" in run[0]["audience"]


def test_neutral_analyte_run_is_doctor_only():
    """WBC has no agreed good direction, so the family tab gets no valence."""
    found = P.find_patterns(series("wbc", [8.0, 11.0, 14.0, 18.0], low=4, high=10))
    run = by_id(found, "rising-run", "wbc")
    assert run and run[0]["audience"] == ["doctor"] and run[0]["severity"] == "info"


# -- rule 2: 24h delta ------------------------------------------------------
def test_delta_fires_on_percent_jump():
    found = P.find_patterns(series("ammonia", [40, 100], low=11, high=51, unit="umol/L"))
    d = by_id(found, "delta-24h", "ammonia")
    assert len(d) == 1 and d[0]["severity"] == "high"   # >50% AND > range width


def test_delta_fires_on_range_width_without_percent():
    """Sodium 138 -> 126 is only 9%, and is the emergency the percent test misses."""
    found = P.find_patterns(series("sodium", [138, 126], low=136, high=145, unit="mmol/L"))
    d = by_id(found, "delta-24h", "sodium")
    assert len(d) == 1 and d[0]["severity"] == "moderate"


def test_falling_delta_is_worded_and_signed_as_a_fall():
    """The percentage printed next to "fell" must not carry a + sign."""
    found = P.find_patterns(series("sodium", [138, 126], low=136, high=145, unit="mmol/L"))
    d = by_id(found, "delta-24h", "sodium")[0]
    assert "fell" in d["headline"] and "rose" not in d["headline"]
    assert "more than its whole normal range" in d["headline"]
    assert "-12 (-9%)" in d["detail"], d["detail"]
    assert "+" not in d["detail"], d["detail"]


def test_small_move_does_not_fire_delta():
    found = P.find_patterns(series("sodium", [138, 136], low=136, high=145))
    assert not by_id(found, "delta-24h")


def test_steady_climb_reports_the_trend_not_every_step():
    """One run, no per-day echoes of the same rise."""
    found = P.find_patterns(series("bilirubin_total", [3.1, 4.8, 6.6, 8.1],
                                   low=0.3, high=1.2, unit="mg/dL"))
    assert by_id(found, "rising-run")
    assert not by_id(found, "delta-24h"), ids(found)


def test_overnight_jump_inside_a_run_still_reported():
    """Suppression is for echoes, not for a step that dwarfs its own trend."""
    found = P.find_patterns(series("ammonia", [40, 48, 160], low=11, high=51))
    d = by_id(found, "delta-24h", "ammonia")
    assert len(d) == 1 and [e["value"] for e in d[0]["evidence"]] == [48, 160]


def test_at_most_one_delta_per_analyte():
    found = P.find_patterns(series("ammonia", [40, 100, 40, 120], low=11, high=51))
    d = by_id(found, "delta-24h", "ammonia")
    assert len(d) == 1
    assert [e["value"] for e in d[0]["evidence"]] == [40, 120]   # the sharpest move


# -- rule 3: reference-range crossings --------------------------------------
def test_leaving_range_fires_high_for_headline_analyte():
    found = P.find_patterns(series("creatinine", [0.9, 2.4], low=0.7, high=1.3, unit="mg/dL"))
    x = by_id(found, "range-exit", "creatinine")
    assert len(x) == 1 and x[0]["severity"] == "high"
    assert "above range" in x[0]["detail"]


def test_returning_to_range_is_reported_as_info():
    found = P.find_patterns(series("creatinine", [2.4, 1.0], low=0.7, high=1.3))
    r = by_id(found, "range-return", "creatinine")
    assert len(r) == 1 and r[0]["severity"] == "info"
    assert "family" in r[0]["audience"]
    assert not by_id(found, "range-exit")


def test_second_exit_is_a_relapse_not_a_first_time():
    """Out, back, out again: only the first one may claim to be the first."""
    found = P.find_patterns(series("creatinine", [0.9, 2.4, 1.0, 2.6],
                                   low=0.7, high=1.3, unit="mg/dL"))
    x = by_id(found, "range-exit", "creatinine")
    assert len(x) == 2, ids(found)
    assert "for the first time" in x[0]["headline"]
    assert x[1]["headline"].endswith("normal range again.")
    assert "first time" not in x[1]["headline"]
    assert len(by_id(found, "range-return", "creatinine")) == 1


def test_no_reference_range_means_no_crossing():
    found = P.find_patterns(series("ammonia", [40, 100]))
    assert not by_id(found, "range-exit")


# -- rule 4: the lab's own critical flag ------------------------------------
def test_critical_flag_is_the_only_source_of_critical():
    o = series("potassium", [4.0, 4.1], low=3.5, high=5.1, unit="mmol/L")
    o.append(obs("potassium", 3, 2.4, 3.5, 5.1, "mmol/L", flag="CL"))
    found = P.find_patterns(o)
    c = by_id(found, "critical-flag", "potassium")
    assert len(c) == 1 and c[0]["severity"] == "critical"
    assert c[0]["evidence"] == [{"day": 3, "value": 2.4}]
    assert found[0]["severity"] == "critical"        # sorted most severe first


def test_resolved_critical_flag_is_not_reported_as_a_live_emergency():
    """The lab flagged day 2 and has measured twice since without flagging.
    Saying "the doctors are alerted immediately" then is telling a family the
    patient is inside an emergency they are already out of."""
    o = series("potassium", [4.0], low=3.5, high=5.1, unit="mmol/L")
    o.append(obs("potassium", 2, 2.4, 3.5, 5.1, "mmol/L", flag="CL"))
    o += series("potassium", [3.6, 4.2], low=3.5, high=5.1, unit="mmol/L", start_day=3)
    c = by_id(P.find_patterns(o), "critical-flag", "potassium")
    assert len(c) == 1
    assert c[0]["severity"] == "high"                  # not critical: it is history
    assert "no longer carries that flag" in c[0]["headline"]
    assert "alerted immediately" not in c[0]["headline"]
    assert "day(s) 2" in c[0]["detail"] and "4.2" in c[0]["detail"]
    assert c[0]["evidence"] == [{"day": 2, "value": 2.4}, {"day": 4, "value": 4.2}]


def test_still_flagged_on_the_latest_sample_stays_critical():
    o = series("potassium", [4.0, 3.6], low=3.5, high=5.1, unit="mmol/L")
    o.append(obs("potassium", 3, 2.4, 3.5, 5.1, "mmol/L", flag="CL"))
    c = by_id(P.find_patterns(o), "critical-flag", "potassium")
    assert len(c) == 1 and c[0]["severity"] == "critical"
    assert "alerted immediately" in c[0]["headline"]


def test_plain_high_flag_is_not_critical():
    o = series("potassium", [4.0, 5.4], low=3.5, high=5.1)
    o[-1]["printed_flag"] = "H"
    assert not by_id(P.find_patterns(o), "critical-flag")


# -- rule 5: MELD 3.0 trajectory --------------------------------------------
def test_meld_escalation():
    scores = [{"day": 1, "collected": "2024-03-04T08:00",
               "meld3": {"value": 24, "complete": True}},
              {"day": 3, "collected": "2024-03-06T08:00",
               "meld3": {"value": 31, "complete": True}}]
    found = P.find_patterns([], scores)
    m = by_id(found, "meld-escalation")
    assert len(m) == 1 and m[0]["severity"] == "high" and m[0]["analyte"] is None


def test_meld_rise_under_threshold_is_silent():
    scores = [{"day": 1, "meld3": {"value": 24, "complete": True}},
              {"day": 2, "meld3": {"value": 26, "complete": True}}]
    assert not by_id(P.find_patterns([], scores), "meld-escalation")


def test_incomplete_meld_is_never_used():
    scores = [{"day": 1, "meld3": {"value": 24, "complete": False}},
              {"day": 2, "meld3": {"value": 40, "complete": False}}]
    assert not by_id(P.find_patterns([], scores), "meld-escalation")


# -- rule 6: synthetic-function cluster -------------------------------------
def _synthetic_obs(albumin):
    return (series("inr", [1.6, 2.2, 2.9])
            + series("albumin", albumin, low=3.5, high=5.2, unit="g/dL")
            + series("bilirubin_total", [4.8, 6.6, 8.1], low=0.3, high=1.2, unit="mg/dL"))


def test_synthetic_cluster_fires():
    found = P.find_patterns(_synthetic_obs([3.0, 2.7, 2.4]))
    s = by_id(found, "synthetic-failure")
    assert len(s) == 1 and s[0]["severity"] == "high" and s[0]["analyte"] == "inr"
    assert {e["analyte"] for e in s[0]["evidence"]} == {"inr", "albumin", "bilirubin_total"}


def test_synthetic_cluster_needs_all_three():
    """Albumin holding steady breaks the cluster even with the other two rising."""
    assert not by_id(P.find_patterns(_synthetic_obs([3.0, 3.0, 3.0])), "synthetic-failure")


# -- rule 7: infection cluster ----------------------------------------------
def _infection_obs(direction=1):
    def d(vals):
        return vals if direction > 0 else list(reversed(vals))
    return (series("procalcitonin", d([1.2, 3.0, 5.0]), low=0, high=0.5)
            + series("crp", d([40, 90, 160]), low=0, high=5)
            + series("wbc", d([9, 14, 20]), low=4, high=10)
            + series("nlr", d([6, 11, 18])))


def test_infection_cluster_fires_when_markers_rise_together():
    found = P.find_patterns(_infection_obs(1))
    c = by_id(found, "infection-cluster")
    assert len(c) == 1 and c[0]["severity"] == "high"    # 4 markers rising


def test_infection_improving_is_info_not_alarm():
    found = P.find_patterns(_infection_obs(-1))
    c = by_id(found, "infection-improving")
    assert len(c) == 1 and c[0]["severity"] == "info"
    assert not by_id(found, "infection-cluster")


def test_two_markers_are_not_a_cluster():
    o = series("crp", [40, 90, 160], low=0, high=5) + series("nlr", [6, 11, 18])
    assert not by_id(P.find_patterns(o), "infection-cluster")


# -- rule 8: renal cluster --------------------------------------------------
def _renal_obs(sodium_key="sodium"):
    return (series("creatinine", [0.9, 1.6, 2.4], low=0.7, high=1.3, unit="mg/dL")
            + series("urea", [30, 55, 80], low=17, high=43, unit="mg/dL")
            + series(sodium_key, [138, 132, 126], low=136, high=145, unit="mmol/L"))


def test_renal_cluster_fires():
    r = by_id(P.find_patterns(_renal_obs()), "renal-cluster")
    assert len(r) == 1 and r[0]["severity"] == "high" and r[0]["analyte"] == "creatinine"


def test_cluster_needs_a_shared_window_not_just_three_tidy_series():
    """Creatinine and urea rise on days 1-3, sodium falls on days 5-7. Every
    analyte moves the required way and none of them moved TOGETHER, which is
    the only thing the cluster claims. Entry-count windows fired here."""
    o = (series("creatinine", [0.9, 1.6, 2.4], low=0.7, high=1.3, unit="mg/dL")
         + series("urea", [30, 55, 80], low=17, high=43, unit="mg/dL")
         + series("sodium", [138, 132, 126], low=136, high=145, unit="mmol/L",
                  start_day=5))
    found = P.find_patterns(o)
    assert not by_id(found, "renal-cluster"), ids(found)
    assert by_id(found, "rising-run", "creatinine")     # the per-analyte rules still speak


def test_renal_cluster_never_substitutes_blood_gas_sodium():
    """abg_sodium is a different specimen and must not stand in for serum."""
    o = _renal_obs("abg_sodium") + series("sodium", [138, 138, 138], low=136, high=145)
    assert not by_id(P.find_patterns(o), "renal-cluster")


# -- rule 9: perfusion ------------------------------------------------------
def test_rising_lactate_above_range_is_high():
    found = P.find_patterns(series("lactate", [1.2, 2.4, 4.0], low=0.5, high=2.2,
                                   unit="mmol/L"))
    p = by_id(found, "perfusion")
    assert len(p) == 1 and p[0]["severity"] == "high"


def test_low_po2_fires_once():
    found = P.find_patterns(series("abg_po2", [95, 88, 62], low=80, high=100, unit="mmHg"))
    p = by_id(found, "low-oxygen")
    assert len(p) == 1 and p[0]["severity"] == "moderate"
    assert p[0]["analyte"] == "abg_po2"


# -- rule 10: discordance ---------------------------------------------------
def test_discordance_is_doctor_only():
    o = _infection_obs(-1) + _synthetic_obs([3.0, 2.7, 2.4])
    found = P.find_patterns(o)
    d = by_id(found, "discordance")
    assert len(d) == 1 and d[0]["audience"] == ["doctor"]
    assert d[0]["severity"] == "moderate"


def test_no_discordance_when_everything_worsens():
    o = _infection_obs(1) + _synthetic_obs([3.0, 2.7, 2.4])
    assert not by_id(P.find_patterns(o), "discordance")


# -- recovery: the direction the family tab must never get backwards ---------
def test_recovering_patient_raises_nothing_above_info():
    """Bilirubin and INR falling, albumin climbing back into range, every
    infection marker settling. Nothing here may read as deterioration."""
    o = (series("bilirubin_total", [8.1, 6.6, 4.8], low=0.3, high=1.2, unit="mg/dL")
         + series("inr", [2.9, 2.2, 1.6])
         + series("albumin", [2.1, 2.8, 3.6], low=3.5, high=5.2, unit="g/dL")
         + _infection_obs(-1))
    found = P.find_patterns(o)
    assert found
    assert {p["severity"] for p in found} == {"info"}, [
        (p["id"], p["severity"]) for p in found if p["severity"] != "info"]
    assert not by_id(found, "synthetic-failure")
    assert by_id(found, "infection-improving")
    # Albumin rising is a rising-run and is good news -- direction is not valence.
    assert "right direction" in by_id(found, "rising-run", "albumin")[0]["headline"]
    bili = by_id(found, "falling-run", "bilirubin_total")[0]
    assert "right direction" in bili["headline"]
    assert "-41%" in bili["detail"], bili["detail"]
    alb = by_id(found, "range-return", "albumin")[0]
    assert "back inside the normal range" in alb["headline"]
    assert "family" in alb["audience"]


# -- shape ------------------------------------------------------------------
def test_every_pattern_matches_the_schema_shape():
    o = (_infection_obs(1) + _renal_obs() + _synthetic_obs([3.0, 2.7, 2.4])
         + series("lactate", [1.2, 2.4, 4.0], low=0.5, high=2.2))
    o.append(obs("potassium", 3, 2.4, 3.5, 5.1, "mmol/L", flag="CL"))
    found = P.find_patterns(o, [{"day": 1, "meld3": {"value": 24, "complete": True}},
                                {"day": 3, "meld3": {"value": 31, "complete": True}}])
    assert found
    keys = {"id", "severity", "analyte", "headline", "detail", "evidence", "audience"}
    import src.config as C
    for p in found:
        assert set(p) == keys, p
        assert p["severity"] in ("critical", "high", "moderate", "info")
        assert p["analyte"] is None or p["analyte"] in C.ANALYTES
        assert p["headline"] and p["detail"] and p["evidence"]
        assert set(p["audience"]) <= {"doctor", "family"}
        for e in p["evidence"]:
            assert set(e) <= {"day", "value", "analyte"}


def test_multiple_samples_in_one_day_collapse_to_the_last():
    o = series("bilirubin_total", [3.1, 4.8, 6.6], low=0.3, high=1.2)
    early = obs("bilirubin_total", 3, 99.0, 0.3, 1.2)
    early["collected"] = "2024-03-06T01:00"          # earlier than the day-3 point
    found = P.find_patterns(o + [early])
    assert [e["value"] for e in by_id(found, "rising-run")[0]["evidence"]] == [3.1, 4.8, 6.6]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} passed")
