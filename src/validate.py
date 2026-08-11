"""Four independent gates that decide whether a value can be trusted.

Owns: reference-range parsing, and the four checks -- OCR ensemble agreement,
consistency with the flag the lab printed, arithmetic identities, and the
physiological envelope.

Does NOT own: OCR, parsing, or the human review ledger.

The gates are deliberately built around things that are true regardless of how
ill the patient is. This patient is severely abnormal on nearly every axis, so
a validator tuned to "does this look plausible" would spend its time flagging
the real clinical signal. An algebraic identity has no such conflict: if
MCV != PCV/RBC*10 then something was misread, whatever the patient's condition.
"""

from __future__ import annotations

import math
import re

from . import config as C

# "10.8 - 13.2" | "0- 54" | "41-51" | "150 - 410" | "1.500 -5" | "13.500 - 18"
RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)")
# "< 0.5" | "Normal <1.3" | "< 1.000" | "> 40"
BOUND_RE = re.compile(r"([<>])\s*=?\s*(-?\d+(?:\.\d+)?)")


def parse_reference(text: str) -> dict:
    """Turn the printed reference interval into {low, high, text}.

    Ranges are tried before single bounds because "10.8 - 13.2" contains no
    comparator, while "Normal <1.3" contains no dash -- checking in the other
    order would read the '-' of a negative bound as a range separator.
    """
    text = (text or "").strip()
    if not text:
        return {"low": None, "high": None, "text": ""}

    m = RANGE_RE.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi:
            return {"low": lo, "high": hi, "text": text}

    m = BOUND_RE.search(text)
    if m:
        op, val = m.group(1), float(m.group(2))
        if op == "<":
            return {"low": None, "high": val, "text": text}
        return {"low": val, "high": None, "text": text}

    return {"low": None, "high": None, "text": text}


def interpret(value: float, ref: dict) -> str | None:
    """FHIR interpretation code implied by the value and its reference range."""
    if value is None:
        return None
    if ref["high"] is not None and value > ref["high"]:
        return "H"
    if ref["low"] is not None and value < ref["low"]:
        return "L"
    if ref["low"] is None and ref["high"] is None:
        return None
    return "N"


# --------------------------------------------------------------------------
# Gate 1 -- ensemble agreement.
# --------------------------------------------------------------------------
def gate_ensemble(ocr_readings: dict[str, float | None]) -> tuple[str, str]:
    got = [v for v in ocr_readings.values() if v is not None]
    if not got:
        return "fail", "no pass produced a value"
    distinct = set(got)
    if len(distinct) == 1:
        return ("pass", "unanimous") if len(got) >= 2 else ("weak", "single pass only")
    # A majority still counts, but it is not unanimous and a human should look.
    winner = max(distinct, key=got.count)
    if got.count(winner) > len(got) / 2:
        return "weak", f"majority {winner} of {sorted(distinct)}"
    return "fail", f"no majority among {sorted(distinct)}"


# --------------------------------------------------------------------------
# Gate 2 -- the printed flag is a redundant encoding of the value.
#
# The lab already told us where the value sits relative to its range. If OCR
# drops a decimal point and reads 38.2 as 3.43, the value falls BELOW the
# range while the page still says (H). Catches the two most damaging OCR
# failures -- decimal placement and dropped digits -- with no clinical
# knowledge required.
# --------------------------------------------------------------------------
def gate_flag(value: float | None, printed_flag: str | None, ref: dict) -> tuple[str, str]:
    if value is None:
        return "skip", "no value"
    implied = interpret(value, ref)
    if implied is None:
        return "skip", "no usable reference range"

    if not printed_flag:
        # No flag printed means the lab considered it normal.
        if implied == "N":
            return "pass", "no flag, value in range"
        return "weak", f"no flag printed but value reads {implied}"

    printed = printed_flag.upper().lstrip("C")   # CH -> H, CL -> L
    if printed == implied:
        return "pass", f"flag {printed_flag} agrees"
    return "fail", f"page says {printed_flag} but value {value} reads {implied} against {ref['text']!r}"


# --------------------------------------------------------------------------
# Gate 3 -- arithmetic identities the analyser itself guarantees.
# --------------------------------------------------------------------------
def _close(a: float, b: float, rel: float = C.REL_TOLERANCE) -> bool:
    if a is None or b is None:
        return False
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale <= rel


IDENTITIES = [
    # (name, required analytes, function returning (expected, actual))
    ("mcv_from_pcv_rbc", ("mcv", "pcv", "rbc"),
     lambda v: (v["pcv"] / v["rbc"] * 10, v["mcv"]) if v["rbc"] else None),
    ("mch_from_hb_rbc", ("mch", "hemoglobin", "rbc"),
     lambda v: (v["hemoglobin"] / v["rbc"] * 10, v["mch"]) if v["rbc"] else None),
    ("mchc_from_hb_pcv", ("mchc", "hemoglobin", "pcv"),
     lambda v: (v["hemoglobin"] / v["pcv"] * 100, v["mchc"]) if v["pcv"] else None),
    ("bilirubin_split", ("bilirubin_total", "bilirubin_direct", "bilirubin_indirect"),
     lambda v: (v["bilirubin_direct"] + v["bilirubin_indirect"], v["bilirubin_total"])),
    ("protein_split", ("protein_total", "albumin", "globulin"),
     lambda v: (v["albumin"] + v["globulin"], v["protein_total"])),
    ("ag_ratio", ("ag_ratio", "albumin", "globulin"),
     lambda v: (v["albumin"] / v["globulin"], v["ag_ratio"]) if v["globulin"] else None),
    ("inr_from_pt", ("inr", "pt", "pt_mnpt"),
     lambda v: ((v["pt"] / v["pt_mnpt"]) ** C.INR_ISI, v["inr"]) if v["pt_mnpt"] else None),
    ("nlr_from_counts", ("nlr", "anc", "alc"),
     lambda v: (v["anc"] / v["alc"], v["nlr"]) if v["alc"] else None),
]


def gate_arithmetic(by_analyte: dict[str, float]) -> dict[str, tuple[str, str]]:
    """Run every identity whose inputs are all present in this sample.

    Returns one verdict per analyte involved, so a violation flags all of its
    participants -- the identity says one of them is wrong, not which.
    """
    verdicts: dict[str, tuple[str, str]] = {}
    for name, needed, fn in IDENTITIES:
        if not all(by_analyte.get(k) is not None for k in needed):
            continue
        got = fn(by_analyte)
        if got is None:
            continue
        expected, actual = got
        ok = _close(expected, actual)
        state = "pass" if ok else "fail"
        detail = f"{name}: expected {expected:.4g}, page says {actual:.4g}"
        for k in needed:
            prev = verdicts.get(k)
            # A failure anywhere outranks a pass elsewhere.
            if prev is None or (prev[0] == "pass" and state == "fail"):
                verdicts[k] = (state, detail)
    return verdicts


def gate_differential(by_analyte: dict[str, float]) -> tuple[str, str] | None:
    """White-cell percentages must sum to about 100.

    The report states this bound itself: "the differential count is computed
    from a total of several thousands of cells... may not add upto exactly 100.
    It may fall between 99 and 101."
    """
    parts = ["neutrophils_pct", "lymphocytes_pct", "monocytes_pct",
             "eosinophils_pct", "basophils_pct"]
    present = [by_analyte[p] for p in parts if by_analyte.get(p) is not None]
    if len(present) < 4:
        return None
    total = sum(present)
    lo, hi = C.DIFFERENTIAL_SUM_RANGE
    if lo <= total <= hi:
        return "pass", f"differential sums to {total:.1f}"
    return "fail", f"differential sums to {total:.1f}, outside {lo}-{hi}"


# --------------------------------------------------------------------------
# Gate 4 -- physiological envelope.
# --------------------------------------------------------------------------
def gate_envelope(analyte: str, value: float | None) -> tuple[str, str]:
    if value is None:
        return "skip", "no value"
    meta = C.ANALYTES.get(analyte)
    if not meta:
        return "skip", "unknown analyte"
    if meta["lo"] <= value <= meta["hi"]:
        return "pass", "within physiological envelope"
    return "fail", f"{value} outside {meta['lo']}..{meta['hi']} for {analyte}"


def consensus_ranges(observations: list[dict]) -> dict[str, dict]:
    """Reference range per analyte, taken from wherever the report printed one.

    The same analyte is printed with its range on most rows but not all -- the
    blood gas omits it for several derived values. Borrowing the range the lab
    itself printed elsewhere for that analyte gives the tiebreaker below
    something to work with on the rows that lack one.
    """
    out: dict[str, dict] = {}
    for o in observations:
        ref = parse_reference(o.get("reference_text", ""))
        if ref["low"] is None and ref["high"] is None:
            continue
        out.setdefault(o["analyte"], ref)
    return out


def choose_value(ocr_readings: dict[str, float | None], ref: dict,
                 printed_flag: str | None, analyte: str) -> float | None:
    """Pick the value the OCR passes best support.

    Majority first. Where the passes tie, or where the majority reading sits
    outside a range the lab printed while a minority reading sits inside it,
    the reference range decides.

    That tiebreak is doing real work here: nearly every disagreement in this
    document is a misplaced decimal point (4.3 read as 43.0, 1.3 as 13.0). One
    of the two candidates is inside the printed range and the other is an order
    of magnitude outside it, so the lab's own printed range separates them
    without any clinical judgement.
    """
    readings = [v for v in ocr_readings.values() if v is not None]
    if not readings:
        return None

    counts = {v: readings.count(v) for v in set(readings)}
    top = max(counts.values())
    leaders = [v for v, n in counts.items() if n == top]
    if len(leaders) == 1 and top > 1:
        candidate = leaders[0]
        if _plausible(candidate, ref, analyte):
            return candidate
        better = [v for v in counts if v != candidate and _plausible(v, ref, analyte)]
        return better[0] if len(better) == 1 else candidate

    plausible = [v for v in counts if _plausible(v, ref, analyte)]
    if len(plausible) == 1:
        return plausible[0]
    # Nothing separates them: pass A is the unmodified read and the default.
    return ocr_readings.get("A") or leaders[0]


def _plausible(value: float, ref: dict, analyte: str) -> bool:
    meta = C.ANALYTES.get(analyte)
    if meta and not (meta["lo"] <= value <= meta["hi"]):
        return False
    lo, hi = ref.get("low"), ref.get("high")
    if lo is None and hi is None:
        return True
    # Allow a wide margin around the reference range: this patient is genuinely
    # abnormal, so the test is "same order of magnitude", not "normal".
    if lo is not None and value < lo / 10:
        return False
    if hi is not None and value > hi * 10:
        return False
    return True


def resolve_decimal_shifts(observations: list[dict]) -> list[dict]:
    """Correct chosen values that are a decimal-point shift off their own series.

    Every remaining OCR disagreement in this document is the same failure: a
    decimal point lost, turning 2.1 into 21.0 or 1.5 into 15.0. Majority voting
    cannot always settle it, because two passes can drop the same decimal.

    What does settle it is the analyte's own distribution. Carboxyhaemoglobin
    reads 1.1, 1.5, 2.2 across the document, so a reading of 21.0 is not a sick
    patient -- it is a missing decimal point. The check only fires when an
    alternative OCR reading sits close to the median AND the chosen value is an
    order of magnitude away, so genuinely extreme values (this patient's
    bilirubin is 14x its reference limit) are untouched.

    Returns the list of corrections made, for the audit trail.
    """
    from statistics import median

    by_analyte: dict[str, list[float]] = {}
    for o in observations:
        if o.get("value") is not None:
            by_analyte.setdefault(o["analyte"], []).append(o["value"])

    corrections = []
    for o in observations:
        chosen = o.get("value")
        series = by_analyte.get(o["analyte"], [])
        if chosen is None or len(series) < 3:
            continue
        mid = median(series)
        if mid <= 0 or chosen <= 0:
            continue
        if chosen / mid < 5 and mid / chosen < 5:
            continue                      # chosen is in family; nothing to do

        alternatives = [v for v in o.get("ocr", {}).values()
                        if v is not None and v != chosen and v > 0]
        better = [v for v in alternatives if 0.33 < v / mid < 3]
        if len(set(better)) != 1:
            continue

        fixed = better[0]
        corrections.append({"page": o["page"], "analyte": o["analyte"],
                            "was": chosen, "now": fixed, "series_median": mid})
        o["value"] = fixed
        o.setdefault("provenance", {})["decimal_shift_corrected"] = {
            "was": chosen, "series_median": mid,
        }
        o["needs_review"] = True
    return corrections


def validate_sample(observations: list[dict]) -> None:
    """Attach gate verdicts to every observation drawn from one sample.

    Mutates in place: each observation gains provenance.gates and an
    `interpretation`, and a `needs_review` flag summarising them.
    """
    by_analyte = {o["analyte"]: o.get("value") for o in observations}
    arithmetic = gate_arithmetic(by_analyte)
    differential = gate_differential(by_analyte)

    for o in observations:
        ref = parse_reference(o.get("reference_text", ""))
        o["reference"] = ref
        interp = interpret(o.get("value"), ref)

        # This lab marks a critical result "(CH)" / "(CL)", which is the FHIR
        # HH / LL concept -- a value the laboratory telephones through, not
        # merely one outside the range. Without this mapping nothing in the
        # dataset ever carries HH or LL, so a doctor view that filters on them
        # prints "no critical values" on the same page as an ammonia of 79
        # flagged CH.
        flag = (o.get("printed_flag") or "").upper()
        if flag == "CH":
            interp = "HH"
        elif flag == "CL":
            interp = "LL"
        o["interpretation"] = interp
        o["critical"] = interp in ("HH", "LL")

        gates = {
            "ensemble": gate_ensemble(o.get("ocr", {})),
            "flag_consistency": gate_flag(o.get("value"), o.get("printed_flag"), ref),
            "envelope": gate_envelope(o["analyte"], o.get("value")),
        }
        if o["analyte"] in arithmetic:
            gates["arithmetic"] = arithmetic[o["analyte"]]
        if differential and o["analyte"].endswith("_pct"):
            gates["differential"] = differential

        o.setdefault("provenance", {})["gates"] = {
            k: {"state": s, "detail": d} for k, (s, d) in gates.items()
        }
        o["needs_review"] = any(s in ("fail", "weak") for s, _ in gates.values())


if __name__ == "__main__":
    # The identity that was hand-checked against page 40 before any of this was
    # written: PT 38.2 s, mean normal PT 12.0 s, printed INR 3.18.
    expected = (38.2 / 12.0) ** C.INR_ISI
    print(f"INR from PT: {expected:.4f} vs printed 3.18 -> close={_close(expected, 3.18)}")
    assert _close(expected, 3.18)

    ref = parse_reference("10.8 - 13.2")
    assert ref == {"low": 10.8, "high": 13.2, "text": "10.8 - 13.2"}, ref
    assert interpret(38.2, ref) == "H"
    assert gate_flag(38.2, "H", ref)[0] == "pass"
    # The failure this gate exists for: a dropped decimal point.
    assert gate_flag(3.43, "H", ref)[0] == "fail"

    assert parse_reference("Normal <1.3")["high"] == 1.3
    assert parse_reference("0- 54") == {"low": 0.0, "high": 54.0, "text": "0- 54"}
    assert gate_envelope("inr", 2.89)[0] == "pass"
    assert gate_envelope("inr", 289.0)[0] == "fail"
    print("OK")
