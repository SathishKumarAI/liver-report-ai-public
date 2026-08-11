"""The deterministic rule engine over the verified time series.

Owns: turning `observations` (and optionally `scores`) from docs/SCHEMA.md into
the `patterns` list -- trend runs, 24h deltas, reference-range crossings, the
lab's own critical flags, MELD escalation, the four clusters (synthetic
function, infection, renal, perfusion), and the discordance between them.

Does NOT own: reading files, computing scores, rendering, or any model call.
Nothing here is a diagnosis; every finding must be reproducible by pointing at
the numbers in its own `evidence` list. A rule needing clinical judgement rather
than arithmetic belongs in the written narrative, where a human signs it (D10).

Severity discipline, and the reason this file is worth having: this patient is
abnormal on nearly every axis, so "abnormal" is not news and never earns
`critical`. `critical` means the laboratory itself flagged the value CH/CL or
HH/LL AND has not measured an unflagged one since -- a flag the patient has
already come out of is history, and reports at `high`. Everything the engine
infers on its own also tops out at `high`. An engine that shouts on every row
gets muted, and the row that mattered is muted with it.

Ids: rising-run, falling-run, delta-24h, range-exit, range-return,
critical-flag, meld-escalation, synthetic-failure, infection-cluster,
infection-improving, renal-cluster, perfusion, low-oxygen, discordance.
`analyte` is null where a finding belongs to no single one (score, discordance);
a cluster carries its lead analyte and names the rest in `evidence`, whose rows
then also carry an `analyte` key.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from . import config as C

# Engine tuning. Lives here, not in config.py, because nothing outside this file
# has any use for it and config.py is the pipeline's contract, not a junk drawer.
# ponytail: move it the day a second module needs to agree on these numbers.
MIN_RUN = 3          # samples in a row, i.e. two consecutive moves
NOISE_REL = 0.03     # a step under 3% of the previous value is jitter, not a move
RUN_MIN_NET = 0.10   # ... and the whole run must add up to 10% to be a trend
DELTA_REL = 0.50     # rule 2: more than 50% in 24h
CLUSTER_WINDOW = 3   # days a cluster looks back over
MELD_JUMP = 3        # points of MELD 3.0 over 48h that count as escalation
CRITICAL_FLAGS = {"CH", "CL", "HH", "LL"}   # what the lab itself calls critical

SEV_RANK = {"critical": 0, "high": 1, "moderate": 2, "info": 3}

# Rising in ANY of these means "more inflammatory signal", which is not the same
# question as WORSE_WHEN_RISING: a falling WBC in sepsis is also bad, so wbc and
# neutrophils_pct are deliberately absent from config's valence sets. The
# infection cluster therefore counts direction, not valence.
INFECTION_MARKERS = ("procalcitonin", "crp", "wbc", "neutrophils_pct", "nlr")
LIVER_MARKERS = ("bilirubin_total", "inr", "albumin")


class Point(NamedTuple):
    """One analyte's value on one day, with everything a message needs."""
    day: int
    value: float
    collected: str
    low: float | None
    high: float | None
    unit: str
    display: str


# ---- series construction and shared helpers ------------------------------
def build_series(observations: list[dict]) -> dict[str, list[Point]]:
    """One point per analyte per day, oldest first.

    Several samples share a day (SCHEMA "Day indexing"), so a day needs one
    representative: the LAST collection of it, the value a clinician was
    reacting to when the day ended. Qualitative results and nulls are dropped --
    a culture result has no trend.
    """
    latest: dict[tuple[str, int], dict] = {}
    for o in observations:
        if o.get("kind") != "quantity" or o.get("value") is None:
            continue
        prev = latest.get(key := (o["analyte"], o["day"]))
        if prev is None or (o.get("collected") or "") >= (prev.get("collected") or ""):
            latest[key] = o
    out: dict[str, list[Point]] = {}
    for (analyte, day), o in sorted(latest.items(), key=lambda kv: kv[0][1]):
        ref = o.get("reference") or {}
        out.setdefault(analyte, []).append(Point(
            day, float(o["value"]), o.get("collected") or "",
            ref.get("low"), ref.get("high"), o.get("unit") or "",
            o.get("display") or C.ANALYTES.get(analyte, {}).get("display", analyte)))
    return out


def _dir(prev: float, cur: float) -> int:
    """+1 up, -1 down, 0 within jitter. Relative, because 0.2 means something
    different for INR than for urea; returning 0 for a near-flat step is what
    stops a stable abnormal value -- this patient has many -- reading as a trend.
    """
    base = abs(prev) or 1.0
    if abs(cur - prev) < NOISE_REL * base:
        return 0
    return 1 if cur > prev else -1


def _valence(analyte: str, direction: int) -> str:
    """'worse', 'better', or 'neutral' for a move in `direction`."""
    up, down = analyte in C.WORSE_WHEN_RISING, analyte in C.WORSE_WHEN_FALLING
    if not (up or down):
        return "neutral"
    return "worse" if (direction > 0) == up else "better"


def _in_range(p: Point) -> bool | None:
    """True inside the printed reference range, None if it has no bounds."""
    if p.low is None and p.high is None:
        return None
    return not ((p.low is not None and p.value < p.low)
                or (p.high is not None and p.value > p.high))


def _n(v: float) -> str:
    return f"{v:g}"


def _unit(p: Point) -> str:
    return f" {p.unit}" if p.unit else ""


def _date(p: Point):
    try:
        return datetime.fromisoformat(p.collected)
    except ValueError:
        return None


def _when(pts: list[Point]) -> str:
    """'04-07 Mar', or a day range when timestamps are unusable."""
    a, b = _date(pts[0]), _date(pts[-1])
    if a is None or b is None:
        return f"day {pts[0].day}" if len(pts) == 1 else f"days {pts[0].day}-{pts[-1].day}"
    if a.date() == b.date():
        return f"{a:%d %b}"
    if a.month == b.month:
        return f"{a:%d}-{b:%d %b}"
    return f"{a:%d %b}-{b:%d %b}"


def _ref(p: Point) -> str:
    if p.low is not None and p.high is not None:
        return f"Reference {_n(p.low)}-{_n(p.high)}."
    if p.high is not None:
        return f"Reference upper limit {_n(p.high)}."
    return f"Reference lower limit {_n(p.low)}." if p.low is not None else ""


def _chain(pts: list[Point]) -> str:
    return " -> ".join(_n(p.value) for p in pts) + _unit(pts[-1])


def _ev(pts: list[Point], analyte: str | None = None) -> list[dict]:
    """Evidence rows. `analyte` is stamped only for multi-analyte patterns,
    where a bare {day, value} would be unreadable."""
    extra = {"analyte": analyte} if analyte else {}
    return [{"day": p.day, "value": p.value} | extra for p in pts]


def _pat(id_, severity, analyte, headline, detail, evidence, audience) -> dict:
    return {"id": id_, "severity": severity, "analyte": analyte, "headline": headline,
            "detail": detail, "evidence": evidence, "audience": audience}


def _last_day(S) -> int:
    """The most recent day anywhere in the record -- the anchor every window shares."""
    return max((p.day for pts in S.values() for p in pts), default=0)


def _trend(S, analyte: str, window: int = CLUSTER_WINDOW) -> tuple[int, list[Point]]:
    """Net direction of one analyte over the last `window` DAYS of the record.

    Days, not samples. Analytes are sampled at wildly different rates here, so
    the last three ENTRIES can span one day for a blood gas and a fortnight for
    a weekly albumin; a cluster built on entry counts asserts that its members
    moved TOGETHER when they may not overlap in time at all.

    The cutoff is anchored to the last day of the WHOLE record, not to each
    analyte's own last day, for the same reason: two analytes each with three
    tidy points, a week apart, share no window and must not combine into one
    finding. An analyte with fewer than two points inside the window is silent.
    """
    tail = [p for p in S.get(analyte) or [] if p.day > _last_day(S) - window]
    if len(tail) < 2:
        return 0, tail
    return _dir(tail[0].value, tail[-1].value), tail


def _voice(valence: str, worse_sev: str) -> tuple[str, list[str]]:
    """Severity and audience for a move of this valence. A neutral analyte
    (WBC, MCV: config asserts no good direction) goes to the doctor only --
    calling a move an improvement the dictionary does not claim invents meaning.
    """
    if valence == "worse":
        return worse_sev, ["doctor", "family"]
    return "info", ["doctor", "family"] if valence == "better" else ["doctor"]


def _summary(pts: list[Point]) -> str:
    return f"{pts[-1].display} {_n(pts[0].value)}->{_n(pts[-1].value)}{_unit(pts[-1])}"


# ---- Rule 1 -- monotonic runs ---------------------------------------------
def _runs(pts: list[Point]) -> list[tuple[list[Point], int]]:
    """Maximal same-direction runs of at least MIN_RUN samples. Both filters
    matter: length alone promotes a jittery flat line, net movement alone
    promotes a single jump that rule 2 already covers.
    """
    out, i = [], 0
    while i < len(pts) - 1:
        d = _dir(pts[i].value, pts[i + 1].value)
        if d == 0:
            i += 1
            continue
        j = i + 1
        while j < len(pts) - 1 and _dir(pts[j].value, pts[j + 1].value) == d:
            j += 1
        run = pts[i:j + 1]
        net = abs(run[-1].value - run[0].value) / (abs(run[0].value) or 1.0)
        if len(run) >= MIN_RUN and net >= RUN_MIN_NET:
            out.append((run, d))
        i = j
    return out


def rule_runs(S) -> list[dict]:
    out = []
    for analyte, pts in S.items():
        for run, d in _runs(pts):
            val = _valence(analyte, d)
            first, last = run[0], run[-1]
            span = last.day - first.day
            pct = (last.value - first.value) / (abs(first.value) or 1.0) * 100
            moved = "risen" if d > 0 else "fallen"
            sev, who = _voice(val, "high" if len(run) >= 5 else "moderate")
            head = f"{last.display} has {moved} at every check for {span} days."
            if val == "better":
                head = head[:-1] + " - it is moving in the right direction."
            detail = (f"{_chain(run)} ({_when(run)}); {pct:+.0f}% over {span} days. "
                      f"{_ref(last)}")
            out.append(_pat("rising-run" if d > 0 else "falling-run", sev, analyte,
                            head, detail.strip(), _ev(run), who))
    return out


# ---- Rule 2 -- day-over-day delta -----------------------------------------
def rule_deltas(S) -> list[dict]:
    """More than 50%, or more than one reference-range width, in 24h. The
    range-width test exists because the percentage test is blind where it
    matters most: sodium falling 138 -> 126 is 9%, and is an emergency.
    At most ONE per analyte, the sharpest move, and a step inside a run rule 1
    already reported is dropped unless it dwarfs that trend -- otherwise a steady
    four-day climb emits a run plus three deltas all saying the same thing,
    which is how a findings tab becomes wallpaper.
    """
    out = []
    for analyte, pts in S.items():
        in_run = {p.day for run, _ in _runs(pts) for p in run}
        steps = []
        for a, b in zip(pts, pts[1:]):
            if b.day - a.day != 1:
                continue
            change = b.value - a.value
            rel = abs(change) / (abs(a.value) or 1.0)
            width = (b.high - b.low) if (b.high is not None and b.low is not None) else None
            big_rel = rel > DELTA_REL
            big_abs = width is not None and abs(change) > width
            echo = a.day in in_run and b.day in in_run and rel <= 2 * DELTA_REL
            if echo or not (big_rel or big_abs):
                continue
            steps.append((rel, a, b, change, width, big_rel, big_abs))
        if steps:
            rel, a, b, change, width, big_rel, big_abs = max(steps, key=lambda s: s[0])
            d = 1 if change > 0 else -1
            val = _valence(analyte, d)
            moved = "rose" if d > 0 else "fell"
            reason = ("more than half its previous value" if big_rel
                      else "more than its whole normal range")
            sev, who = _voice(val, "high" if (big_rel and big_abs) else "moderate")
            out.append(_pat(
                "delta-24h", sev, analyte,
                f"{b.display} {moved} by {reason} in one day.",
                f"{_n(a.value)} -> {_n(b.value)}{_unit(b)} "
                # Signed, not `rel`: `rel` is an absolute ratio, so printing it
                # rendered sodium 138 -> 126 as "-12 (+9%)" -- a fall labelled
                # with a rise, on the family tab, next to the word "fell".
                f"({_when([a, b])}); {change:+g} "
                f"({change / (abs(a.value) or 1.0) * 100:+.0f}%)"
                + (f", range width {_n(width)}" if width is not None else "")
                + f". {_ref(b)}".rstrip(),
                _ev([a, b]), who))
    return out


# ---- Rule 3 -- reference-range crossings. Recovery is news too ------------
def rule_crossings(S) -> list[dict]:
    out = []
    for analyte, pts in S.items():
        exits = 0
        for a, b in zip(pts, pts[1:]):
            ina, inb = _in_range(a), _in_range(b)
            if ina is None or inb is None or ina == inb:
                continue
            # A headline analyte leaving normal changes the clinical picture;
            # the rest are reported, not escalated. Coming back is always info.
            left = ina and not inb
            # "for the first time" is true exactly once. A value that has been
            # out, come back and gone again is a relapse, and calling a relapse
            # a first occurrence hides the one thing that made it worth reading.
            if left:
                exits += 1
                head = (f"{b.display} has moved out of the normal range"
                        + (" for the first time." if exits == 1 else " again."))
            else:
                head = f"{b.display} is back inside the normal range."
            side = "above" if (b.high is not None and b.value > b.high) else "below"
            out.append(_pat(
                "range-exit" if left else "range-return",
                ("high" if analyte in C.HEADLINE else "moderate") if left else "info",
                analyte,
                head,
                f"{_n(a.value)} -> {_n(b.value)} "
                f"({side + ' range' if left else 'within reference'})"
                f"{_unit(b)} ({_when([a, b])}). {_ref(b)}",
                _ev([a, b]), ["doctor", "family"]))
    return out


# ---- Rule 4 -- the laboratory's own critical flag. The only source of `critical` ---
def rule_critical(observations: list[dict]) -> list[dict]:
    by_analyte: dict[str, list[dict]] = {}
    seen: dict[str, list[dict]] = {}
    for o in observations:
        if o.get("value") is None:
            continue
        seen.setdefault(o["analyte"], []).append(o)
        flags = {str(o.get("printed_flag") or "").strip().upper(),
                 str(o.get("interpretation") or "").strip().upper()}
        if flags & CRITICAL_FLAGS:
            by_analyte.setdefault(o["analyte"], []).append(o)
    out = []
    for analyte, obs in by_analyte.items():
        obs.sort(key=lambda o: o["day"])
        last = obs[-1]
        # A flag is a fact about a moment, not a standing state. If the lab has
        # measured this analyte again since and did NOT flag it, "the doctors
        # are alerted immediately" is false and the tab is telling a family the
        # patient is in an emergency they have already come out of. Severity
        # follows: `critical` is reserved for a flag that is still the last word.
        latest = max(seen[analyte], key=lambda o: (o["day"], o.get("collected") or ""))
        resolved = latest["day"] > last["day"]
        disp = last.get("display") or C.ANALYTES.get(analyte, {}).get("display", analyte)
        unit = f" {last['unit']}" if last.get("unit") else ""
        ref = last.get("reference") or {}
        bounds = (f"; reference {_n(ref['low'])}-{_n(ref['high'])}."
                  if ref.get("low") is not None and ref.get("high") is not None else ".")
        days = ", ".join(str(o["day"]) for o in obs)
        flag = last.get("printed_flag") or last.get("interpretation")
        ev = [{"day": o["day"], "value": o["value"]} for o in obs]
        if resolved:
            head = (f"The laboratory marked {disp.lower()} as a critical result "
                    f"earlier in this admission; the most recent measurement no "
                    f"longer carries that flag.")
            detail = (f"{disp} {_n(float(last['value']))}{unit} flagged {flag} on "
                      f"day(s) {days}; latest {_n(float(latest['value']))}{unit} on "
                      f"day {latest['day']} is unflagged{bounds}")
            ev = ev + [{"day": latest["day"], "value": latest["value"]}]
        else:
            head = (f"The laboratory marked {disp.lower()} as a critical result, "
                    f"which means the doctors are alerted immediately.")
            detail = (f"{disp} {_n(float(last['value']))}{unit} flagged {flag} "
                      f"on day(s) {days}{bounds}")
        out.append(_pat("critical-flag", "high" if resolved else "critical", analyte,
                        head, detail, ev, ["doctor", "family"]))
    return out


# ---- Rule 5 -- MELD 3.0 trajectory ----------------------------------------
def rule_meld(scores: list[dict]) -> list[dict]:
    """A rise of MELD_JUMP points inside 48h. Incomplete scores are ignored
    outright -- a score computed from a substituted input is not a data point
    (D9)."""
    pts = sorted((s["day"], float(s["meld3"]["value"])) for s in scores
                 if (s.get("meld3") or {}).get("complete")
                 and (s.get("meld3") or {}).get("value") is not None)
    # Largest rise inside any 48h window, not the first one found.
    best = max(((val - pval, pday, pval, day, val)
                for i, (day, val) in enumerate(pts) for pday, pval in pts[:i]
                if 0 < day - pday <= 2 and val - pval >= MELD_JUMP), default=None)
    if best is None:
        return []
    _rise, pday, pval, day, val = best
    return [_pat(
        "meld-escalation", "high", None,
        "The overall liver-failure score has climbed sharply over two days.",
        f"MELD 3.0 {_n(pval)} (day {pday}) -> {_n(val)} (day {day}), "
        f"+{_n(val - pval)} points in {day - pday} day(s).",
        [{"day": pday, "value": pval}, {"day": day, "value": val}],
        ["doctor", "family"])]


# ---- Rules 6-9 -- clusters. Each carries a lead analyte so `analyte` stays a
# valid ANALYTES key; the other members are named in `evidence`.
def _conjunction(S, id_, lead, spec: dict[str, int], headline, gloss, note="") -> list[dict]:
    """One pattern, fired only when EVERY analyte in `spec` moves its way.
    All-or-nothing on purpose: two of three is a coincidence, three of three is
    a picture, and a partial match is already covered by the per-analyte rules.
    """
    tails = {}
    for analyte, want in spec.items():
        d, tail = _trend(S, analyte)
        if d != want:
            return []
        tails[analyte] = tail
    ev = [e for a, t in tails.items() for e in _ev(t, a)]
    parts = ", ".join(_summary(t) for t in tails.values())
    # The span every member actually covers, not whichever analyte happened to
    # be first in the spec -- "over 04-06 Mar" is a claim about all of them.
    edges = sorted((p for t in tails.values() for p in (t[0], t[-1])), key=lambda p: p.day)
    when = _when([edges[0], edges[-1]])
    return [_pat(id_, "high", lead, headline,
                 f"{gloss} over {when}: {parts}. {note}".strip(),
                 ev, ["doctor", "family"])]


def rule_synthetic(S) -> list[dict]:
    return _conjunction(
        S, "synthetic-failure", "inr",
        {"inr": 1, "albumin": -1, "bilirubin_total": 1},
        "Three separate signs of the liver's manufacturing work are moving the "
        "wrong way at the same time.",
        "Clotting time up, protein production down, pigment clearance down")


def _moves(S, analytes) -> dict[str, tuple[int, list[Point]]]:
    """Direction and window per analyte, skipping those with too little data."""
    got = {a: _trend(S, a) for a in analytes}
    return {a: (d, tail) for a, (d, tail) in got.items() if len(tail) >= 2}


def rule_infection(S) -> list[dict]:
    have = _moves(S, INFECTION_MARKERS)
    if len(have) < 3:
        return []
    up, down = (sum(d > 0 for d, _ in have.values()),
                sum(d < 0 for d, _ in have.values()))
    moving = {a: t for a, (d, t) in have.items() if d}
    ev = [e for a, t in moving.items() for e in _ev(t, a)]
    parts = ", ".join(_summary(t) for t in moving.values())
    if up >= 3:
        return [_pat(
            "infection-cluster", "high" if up >= 4 else "moderate", "procalcitonin",
            "Several infection markers are rising together.",
            f"{up} of {len(have)} infection markers rising: {parts}.",
            ev, ["doctor", "family"])]
    if down >= 3 and up == 0:
        return [_pat(
            "infection-improving", "info", "procalcitonin",
            # Not "all settling": the rule allows a marker sitting flat, and the
            # count in the detail is the honest version of the same sentence.
            "The infection markers are settling - the treatment for the "
            "infection appears to be working.",
            f"{down} of {len(have)} infection markers falling: {parts}.",
            ev, ["doctor", "family"])]
    return []


def rule_renal(S) -> list[dict]:
    """`sodium`, never `abg_sodium`: different specimen and method (SCHEMA).
    Substituting the blood-gas value is the same error that would corrupt MELD.
    """
    return _conjunction(
        S, "renal-cluster", "creatinine",
        {"creatinine": 1, "urea": 1, "sodium": -1},
        "The kidneys are struggling as well as the liver, and the salt level in "
        "the blood is falling with it.",
        "Creatinine and urea rising with serum sodium falling -- the hepatorenal pattern",
        "Direction only; the cause needs clinical correlation.")


def rule_perfusion(S) -> list[dict]:
    out = []
    lac_d, lac = _trend(S, "lactate")
    if lac_d > 0:
        last = lac[-1]
        out.append(_pat(
            "perfusion",
            "high" if (last.high is not None and last.value > last.high) else "moderate",
            "lactate",
            "Lactate is rising, which is a sign that the body's tissues are not "
            "getting enough oxygen.",
            f"Lactate {_chain(lac)} ({_when(lac)}). {_ref(last)}".strip(),
            _ev(lac), ["doctor", "family"]))
    po2 = S.get("abg_po2") or []
    if po2 and po2[-1].low is not None and po2[-1].value < po2[-1].low:
        last = po2[-1]
        out.append(_pat(
            "low-oxygen", "moderate", "abg_po2",
            "The oxygen level measured in arterial blood is below the normal range.",
            f"pO2 {_n(last.value)}{_unit(last)} ({_when([last])}). {_ref(last)}",
            _ev([last]), ["doctor", "family"]))
    return out


# ---- Rule 10 -- discordance. Doctor-only: it is a question, not a finding ---
def rule_discordance(S) -> list[dict]:
    have = _moves(S, INFECTION_MARKERS)
    liver = _moves(S, LIVER_MARKERS)
    if len(have) < 2:
        return []
    inf_up, inf_down = (sum(d > 0 for d, _ in have.values()),
                        sum(d < 0 for d, _ in have.values()))
    val = [_valence(a, d) for a, (d, _) in liver.items() if d]
    liv_worse, liv_better = val.count("worse"), val.count("better")
    n = len(liver)   # markers MEASURED in the window, not the three we hoped for
    if inf_down >= 2 and inf_up == 0 and liv_worse >= 2:
        head = "The infection is settling, but the liver numbers are still getting worse."
        detail = (f"{inf_down} of {len(have)} infection markers falling while {liv_worse} "
                  f"of {n} liver markers worsen over the same window: the liver injury "
                  f"is not tracking the infection.")
    elif inf_up >= 2 and liv_better >= 2 and liv_worse == 0:
        head = "The liver numbers are improving, but the infection markers are going up."
        detail = (f"{inf_up} of {len(have)} infection markers rising while {liv_better} "
                  f"of {n} liver markers improve over the same window: raises the "
                  f"question of a new or uncontrolled infective source.")
    else:
        return []
    ev = [e for a, (_, t) in (*have.items(), *liver.items()) for e in _ev(t, a)]
    return [_pat("discordance", "moderate", None, head, detail, ev, ["doctor"])]


# ---- Entry point ----------------------------------------------------------
def find_patterns(observations: list[dict], scores: list[dict] | None = None) -> list[dict]:
    """Every rule, most severe first. Pure function of its inputs."""
    S = build_series(observations)
    out = (rule_runs(S) + rule_deltas(S) + rule_crossings(S)
           + rule_critical(observations) + rule_meld(scores or [])
           + rule_synthetic(S) + rule_infection(S) + rule_renal(S)
           + rule_perfusion(S) + rule_discordance(S))
    out.sort(key=lambda p: (SEV_RANK[p["severity"]], p["id"], p["analyte"] or ""))
    return out


if __name__ == "__main__":
    # Eyeball the real dataset. The runnable check lives in tests/test_patterns.py.
    import json

    doc = json.loads(C.LABS_JSON.read_text(encoding="utf-8"))
    for p in find_patterns(doc.get("observations", []), doc.get("scores", [])):
        print(f"[{p['severity']:>8}] {p['id']:<18} {p['headline']}")
