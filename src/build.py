"""Assemble the dataset and render the dashboard.

Owns: joining observations to samples, running the validation gates, computing
scores and patterns per day, generating evidence crops, writing data/labs.json,
and emitting dist/dashboard.html.

Does NOT own: OCR, parsing, or presentation markup (src/dashboard_assets.py).

The export gate lives here on purpose: a rule that says "every charted value
must be human-verified" is only a rule if something enforces it. See
`check_verification`.
"""

from __future__ import annotations

import difflib
import json
from collections import defaultdict

from . import config as C, crops, dashboard_assets as DA, patterns, scores, validate


def _day_index(collected: str, first_day: str) -> int:
    from datetime import date
    a = date.fromisoformat(first_day)
    b = date.fromisoformat(collected[:10])
    return (b - a).days + 1


def _display_unit(printed: str, canonical: str, obs: dict, prov: dict) -> str:
    """Choose the unit to show: a cleaned-up canonical, or the printed one.

    The canonical unit exists to repair OCR damage -- wrapped units arrive as
    "10^3/mm* 3", letters get mauled into "cellsfcumm". But substituting it
    blindly is dangerous: if the dictionary's unit is simply WRONG for this
    report, the substitution replaces a correct printed unit with a wrong one
    and nothing complains.

    That happened. Total WBC is printed "11800 ... cells/cumm" and the
    dictionary declared "10^3/mm^3", so the dashboard rendered
    "11800 10^3/mm^3" -- overstating the white cell count a thousandfold.

    So: substitute only when the printed unit is recognisably a damaged version
    of the canonical one. When the two genuinely disagree, keep what the page
    says and flag it, because a real disagreement means the dictionary is wrong
    about this analyte and a human needs to look.
    """
    if not printed:
        return canonical

    def squash(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    a, b = squash(printed), squash(canonical)
    if a == b:
        return canonical
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.7:
        return canonical                      # printed is a mangled canonical

    # They genuinely differ. Which one to believe depends on whether what the
    # page says is a real unit at all: "mEq/L" against a dictionary saying
    # "mmol/L" means the dictionary is wrong about this analyte, while "arnitg"
    # against "mmHg" is just OCR damage on a unit we already know.
    known = {squash(u) for u in C.KNOWN_UNITS}
    if a in known:
        prov["unit_mismatch"] = {"printed": printed, "expected": canonical}
        obs["needs_review"] = True
        return printed
    return canonical


def _fmt(v: float) -> str:
    return f"{v:g}"


def build_glossary(observations: list[dict]) -> list[dict]:
    """Per-analyte plain-English entry, including what THIS patient's did.

    A glossary that only defines the test ("bilirubin is a pigment") leaves the
    reader to do the comparison themselves. Saying what the number actually did
    over the week, in words, is the part a worried family can use.

    Deliberately descriptive, never interpretive: it reports direction and
    position against the printed range and stops there. No severity language,
    no prognosis, no advice.
    """
    series: dict[str, list[dict]] = {}
    for o in observations:
        if o.get("value") is not None:
            series.setdefault(o["analyte"], []).append(o)

    entries = []
    for key, rows in series.items():
        meta = C.ANALYTES.get(key)
        if not meta:
            continue
        rows.sort(key=lambda o: o["collected"])
        vals = [r["value"] for r in rows]
        first, last = vals[0], vals[-1]
        ref = rows[-1].get("reference") or {}
        lo, hi = ref.get("low"), ref.get("high")

        if len(vals) == 1:
            course = f"Measured once: {_fmt(first)} {rows[-1].get('unit','')}".strip() + "."
        else:
            spread = max(vals) - min(vals)
            scale = max(abs(first), 1e-9)
            if spread == 0 or abs(last - first) / scale < 0.05:
                move = "little overall change"
            elif last > first:
                move = "higher than at the start"
            else:
                move = "lower than at the start"
            course = (f"Measured {len(vals)} times: {_fmt(first)} to {_fmt(last)} "
                      f"{rows[-1].get('unit','')}".strip() + f", ending {move}.")

        if lo is not None and hi is not None:
            course += f" The normal range printed on the report is {_fmt(lo)} to {_fmt(hi)}."
        elif hi is not None:
            course += f" The report gives normal as under {_fmt(hi)}."
        elif lo is not None:
            course += f" The report gives normal as above {_fmt(lo)}."

        outside = sum(1 for r in rows if r.get("interpretation") in ("H", "L", "HH", "LL"))
        if outside == len(rows) and outside:
            course += " Every reading sat outside that range."
        elif outside:
            course += f" {outside} of {len(rows)} readings sat outside that range."

        if any(r.get("critical") for r in rows):
            course += (" The laboratory marked this a critical result, which means it is "
                       "telephoned to the doctors rather than simply filed.")

        entries.append({
            "key": key, "label": meta["display"], "group": meta.get("group", ""),
            "plain": meta["plain"], "course": course,
        })

    order = list(C.GROUPS)
    entries.sort(key=lambda e: (order.index(e["group"]) if e["group"] in order else 99,
                                e["label"]))
    return entries


# Analytes carried into the multivariate views, by organ system. Deliberately a
# short list: putting all 68 on one chart produces a picture nobody can read.
SYSTEMS = {
    "Liver": ["bilirubin_total", "ast", "albumin", "ammonia"],
    "Clotting": ["inr", "pt", "platelets"],
    "Kidney": ["creatinine", "urea", "sodium"],
    "Infection": ["wbc", "neutrophils_pct", "nlr", "procalcitonin", "crp"],
    "Oxygen": ["lactate", "abg_po2", "abg_hco3"],
}


def _fold_outside(value, ref) -> float | None:
    """How many times outside its own reference range a value sits.

    1.0 means inside the range, 2.0 means twice the upper limit (or half the
    lower one). This is the only way to put bilirubin (ceiling 1.2) and urea
    (ceiling 43) on one axis and have the comparison mean anything -- raw units
    would make bilirubin invisible and urea the whole chart.
    """
    if value is None or value <= 0:
        return None
    lo, hi = (ref or {}).get("low"), (ref or {}).get("high")
    if hi is not None and value > hi and hi > 0:
        return value / hi
    if lo is not None and value < lo and value > 0:
        return lo / value
    if lo is None and hi is None:
        return None
    return 1.0


def build_multivariate(observations: list[dict], days: list[str]) -> dict:
    """Cross-analyte views: normalised trajectories, system burden, coupling.

    Honest about its own limits. This is ONE patient over EIGHT days, so nothing
    here is inferential -- no p-values, no fitted models, no claims about cause.
    Every view is a different way of looking at the same measured numbers.
    """
    from statistics import mean

    from datetime import date as _date

    latest: dict[str, dict[str, dict]] = {}
    for o in observations:
        if o.get("value") is None:
            continue
        day = o["collected"][:10]
        prev = latest.setdefault(o["analyte"], {}).get(day)
        if prev is None or o["collected"] > prev["collected"]:
            latest[o["analyte"]][day] = o

    # Carry a value forward up to two days, exactly as the daily scores do.
    #
    # Without this the per-system summary is meaningless: on 08 Mar the liver
    # group had only ammonia measured and on 10 Mar it had bilirubin too, so the
    # composite jumped from 1.5x to 10.5x purely because a different test was
    # run. That reads as the liver deteriorating when nothing about the liver
    # changed. Carrying forward keeps the composition of each bar stable, and
    # anything carried is marked so a reader can tell a fresh result from a
    # repeated one.
    CARRY = 2
    for key, per_day in latest.items():
        measured = sorted(per_day)
        for day in days:
            if day in per_day:
                continue
            earlier = [m for m in measured if m < day]
            if not earlier:
                continue
            src = earlier[-1]
            age = (_date.fromisoformat(day) - _date.fromisoformat(src)).days
            if age <= CARRY:
                per_day[day] = dict(per_day[src], carried_from=src, carried_days=age)

    # ---- normalised trajectories, one line per analyte ----
    tracks = []
    for system, keys in SYSTEMS.items():
        for key in keys:
            per_day = latest.get(key) or {}
            points = []
            for i, day in enumerate(days):
                o = per_day.get(day)
                if not o:
                    continue
                fold = _fold_outside(o["value"], o.get("reference"))
                if fold is None:
                    continue
                points.append({"i": i, "day": day, "value": o["value"],
                               "fold": round(fold, 3),
                               "carried": bool(o.get("carried_from"))})
            if len(points) >= 2:
                tracks.append({
                    "key": key, "label": C.ANALYTES[key]["display"],
                    "system": system, "points": points,
                })

    # ---- per-system burden per day: mean fold across that system's analytes ----
    burden = []
    for day_i, day in enumerate(days):
        row = {"day": day, "i": day_i, "systems": {}}
        for system, keys in SYSTEMS.items():
            folds, fresh, names = [], 0, []
            for key in keys:
                o = (latest.get(key) or {}).get(day)
                if not o:
                    continue
                f = _fold_outside(o["value"], o.get("reference"))
                if f is None:
                    continue
                folds.append(f)
                names.append(C.ANALYTES[key]["display"])
                if not o.get("carried_from"):
                    fresh += 1
            if folds:
                row["systems"][system] = {
                    "fold": round(mean(folds), 3), "n": len(folds),
                    "fresh": fresh, "tests": names,
                }
        burden.append(row)

    # ---- coupling: two pairs whose relationship is clinically meaningful ----
    def pair(a: str, b: str) -> dict | None:
        pts = []
        for i, day in enumerate(days):
            oa = (latest.get(a) or {}).get(day)
            ob = (latest.get(b) or {}).get(day)
            if oa and ob:
                pts.append({"i": i, "day": day, "x": oa["value"], "y": ob["value"]})
        if len(pts) < 3:
            return None
        return {
            "x_key": a, "y_key": b,
            "x_label": C.ANALYTES[a]["display"], "y_label": C.ANALYTES[b]["display"],
            "x_unit": C.ANALYTES[a]["unit"], "y_unit": C.ANALYTES[b]["unit"],
            "points": pts,
        }

    couples = [p for p in (pair("creatinine", "urea"),
                           pair("bilirubin_total", "inr"),
                           pair("wbc", "nlr")) if p]

    return {"tracks": tracks, "burden": burden, "couples": couples,
            "systems": list(SYSTEMS)}


def build_analytics(observations: list[dict], days: list[str], mv: dict) -> dict:
    """Summary-level aggregates: system state, direction of travel, data quality.

    These exist so the text-heavy tabs can lead with a picture. Every figure is a
    count or a ratio over the verified values -- nothing modelled, nothing fitted.
    """
    series: dict[str, list[dict]] = {}
    for o in observations:
        if o.get("value") is not None:
            series.setdefault(o["analyte"], []).append(o)
    for rows in series.values():
        rows.sort(key=lambda r: r["collected"])

    # ---- direction of travel per analyte, only where "better" is defined ----
    movement = []
    for key, rows in series.items():
        if len(rows) < 2:
            continue
        first, last = rows[0]["value"], rows[-1]["value"]
        if first == 0:
            continue
        change = (last - first) / abs(first)
        if abs(change) < 0.05:
            direction = "flat"
        elif key in C.WORSE_WHEN_RISING:
            direction = "worse" if last > first else "better"
        elif key in C.WORSE_WHEN_FALLING:
            direction = "worse" if last < first else "better"
        else:
            direction = "changed"          # no clinical direction defined
        movement.append({
            "key": key, "label": C.ANALYTES[key]["display"],
            "group": C.ANALYTES[key].get("group", ""),
            "first": first, "last": last,
            "pct": round(change * 100, 1), "direction": direction,
            "n": len(rows),
        })
    # Keep a deep list: the dashboard filters to the directional ones, and a
    # short slice here left only four movers on screen because most of the
    # biggest percentage swings are tests with no defined better/worse.
    movement.sort(key=lambda m: -abs(m["pct"]))

    tally = {k: 0 for k in ("better", "worse", "flat", "changed")}
    for m in movement:
        tally[m["direction"]] += 1

    # ---- current state per organ system, from the multivariate burden ----
    burden = mv.get("burden") or []
    systems = []
    if burden:
        latest_row = burden[-1]
        first_row = next((b for b in burden if b["systems"]), latest_row)
        for system in mv.get("systems", []):
            now = (latest_row["systems"] or {}).get(system)
            then = (first_row["systems"] or {}).get(system)
            if not now:
                continue
            systems.append({
                "system": system, "fold": now["fold"], "n": now["n"],
                "fresh": now.get("fresh", 0),
                "first_fold": then["fold"] if then else None,
            })

    # ---- data quality, for the Validation tab ----
    gate_tally: dict[str, dict[str, int]] = {}
    agreement = {"unanimous": 0, "majority": 0, "single": 0, "conflict": 0}
    for o in observations:
        if o.get("value") is None:
            continue
        readings = [v for v in (o.get("provenance", {}).get("ocr") or {}).values()
                    if v is not None]
        distinct = set(readings)
        if len(readings) >= 2 and len(distinct) == 1:
            agreement["unanimous"] += 1
        elif len(readings) == 1:
            agreement["single"] += 1
        elif distinct and readings.count(max(distinct, key=readings.count)) > len(readings) / 2:
            agreement["majority"] += 1
        else:
            agreement["conflict"] += 1
        for gate, verdict in (o.get("provenance", {}).get("gates") or {}).items():
            slot = gate_tally.setdefault(gate, {})
            state = verdict.get("state", "skip")
            slot[state] = slot.get(state, 0) + 1

    charted = sum(1 for o in observations if o.get("value") is not None)
    verified = sum(1 for o in observations
                   if o.get("value") is not None
                   and o.get("provenance", {}).get("human_verified"))

    # ---- what changed on each day ----
    per_day = []
    for i, day in enumerate(days):
        newly, improved, worsened = [], [], []
        for key, rows in series.items():
            today = [r for r in rows if r["collected"][:10] == day]
            if not today:
                continue
            now = today[-1]
            earlier = [r for r in rows if r["collected"][:10] < day]
            was = earlier[-1] if earlier else None
            out_now = now.get("interpretation") in ("H", "L", "HH", "LL")
            if was is None:
                if out_now:
                    newly.append(key)
                continue
            out_before = was.get("interpretation") in ("H", "L", "HH", "LL")
            if out_now and not out_before:
                newly.append(key)
            base = abs(was["value"]) or 1
            delta = (now["value"] - was["value"]) / base
            if abs(delta) < 0.05:
                continue
            if key in C.WORSE_WHEN_RISING:
                (worsened if delta > 0 else improved).append(key)
            elif key in C.WORSE_WHEN_FALLING:
                (improved if delta > 0 else worsened).append(key)
        per_day.append({
            "day": day, "i": i,
            "newly_abnormal": len(newly), "improved": len(improved),
            "worsened": len(worsened),
            "newly_names": [C.ANALYTES[k]["display"] for k in newly[:6]],
        })

    return {
        "movement": movement[:40], "tally": tally, "systems": systems,
        "quality": {"agreement": agreement, "gates": gate_tally,
                    "charted": charted, "verified": verified},
        "per_day": per_day,
    }


FORMULA_DISPLAY_NAMES = {
    "meld3": "MELD 3.0", "meld_na": "MELD-Na", "child_pugh": "Child-Pugh",
    "aarc": "AARC (APASL)", "nlr": "Neutrophil:lymphocyte ratio",
    "anion_gap": "Anion gap", "maddrey_df": "Maddrey discriminant function",
}


def build_formula_cards(latest: dict) -> list[dict]:
    """Formula cards for the Formulas tab, from the scoring module's own docs.

    Shared by the OCR path and the synthetic demo, so the equation a reader sees
    is always the equation the code runs, whichever produced the dataset.
    """
    cards = []
    for key, doc in getattr(scores, "FORMULA_DOCS", {}).items():
        clinical = doc.get("clinical", "")
        row = (latest or {}).get(key)

        # Caveats the scoring module attaches to its own result -- for example
        # that AARC used the blood-gas lactate rather than a serum assay --
        # belong on the card a clinician reads, not only in the JSON.
        if isinstance(row, dict):
            for note in row.get("notes", []) or []:
                if note not in clinical:
                    clinical = f"{clinical} Note: {note}."

        card = {
            "name": FORMULA_DISPLAY_NAMES.get(
                key, doc.get("name") or key.replace("_", " ").title()),
            "expression": doc.get("formula", ""),
            "plain": doc.get("plain", ""),
            "clinical": clinical,
            "source": doc.get("source", ""),
        }
        if isinstance(row, dict) and not row.get("complete", True):
            card["missing"] = row.get("missing", [])
        cards.append(card)
    return cards


def dedupe(observations: list[dict]) -> list[dict]:
    """One observation per (analyte, sample).

    A panel that spans two pages repeats its analytes, and continuation pages
    inherit the same sample, so the same measurement arrives more than once.
    Left in, every chart sees a value followed by an identical copy of itself,
    every day-over-day delta computes as zero, and the whole dashboard reports
    "unchanged" for a patient whose bilirubin moved 14.6 -> 18.0.

    Where duplicates DISAGREE the disagreement is real evidence of an OCR
    problem, so the survivor keeps the better-supported reading and is flagged
    for review rather than silently picking one.
    """
    best: dict[tuple, dict] = {}
    for o in observations:
        key = (o["analyte"], o.get("collected"))
        prev = best.get(key)
        if prev is None:
            best[key] = o
            continue

        conflict = (prev.get("value") != o.get("value")
                    and None not in (prev.get("value"), o.get("value")))

        def support(x):
            readings = [v for v in x.get("ocr", {}).values() if v is not None]
            unanimous = len(set(readings)) == 1 and len(readings) > 1
            return (unanimous, len(readings), not x.get("needs_review", False))

        winner = o if support(o) > support(prev) else prev
        loser = prev if winner is o else o
        if conflict:
            winner["needs_review"] = True
            winner.setdefault("provenance", {}).setdefault("conflicts", []).append({
                "page": loser["page"], "value": loser.get("value"),
            })
        best[key] = winner
    return list(best.values())


def assemble(raw: dict, make_crops: bool = True) -> dict:
    observations = [o for o in raw["observations"] if o.get("collected")]

    # Re-derive the analyte from the printed test name on every build.
    #
    # The mapping is assigned during parsing, so without this a correction to
    # the analyte dictionary would need a full re-OCR of all 112 pages to take
    # effect. Re-deriving here makes config.ANALYTES authoritative at build
    # time, which is what let the Hct/PCV specimen mix-up be fixed by editing
    # one dictionary entry rather than reprocessing the document.
    from . import parse as parse_mod
    for o in observations:
        rederived = parse_mod.match_analyte(o.get("raw_test", ""))
        if rederived and rederived != o["analyte"]:
            o["analyte"] = rederived
            meta = C.ANALYTES[rederived]
            o["display"] = meta["display"]

    # Re-vote every value across ALL OCR passes before anything else looks at it.
    # extract.py chose a value from the passes it had at the time; the digit
    # whitelisted pass is added afterwards by tools/value_pass.py, so without
    # this the third reading would be recorded and never counted.
    ranges = validate.consensus_ranges(observations)
    for o in observations:
        ref = validate.parse_reference(o.get("reference_text", "")) or {}
        if ref.get("low") is None and ref.get("high") is None:
            ref = ranges.get(o["analyte"], ref)
        o["value"] = validate.choose_value(o.get("ocr", {}), ref,
                                           o.get("printed_flag"), o["analyte"])

    corrections = validate.resolve_decimal_shifts(observations)
    for c in corrections:
        print(f"  decimal shift: p{c['page']:03d} {c['analyte']} "
              f"{c['was']} -> {c['now']} (series median {c['series_median']})")

    observations = dedupe(observations)

    # Gates run per sample, because the arithmetic identities only make sense
    # between analytes measured on the same specimen.
    by_sample: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        by_sample[o["collected"]].append(o)
    for group in by_sample.values():
        validate.validate_sample(group)

    days = sorted({o["collected"][:10] for o in observations})
    first_day = days[0] if days else None

    from .render import analyse_page
    page_size_cache: dict[int, tuple[int, int]] = {}

    # The human verification ledger. Kept outside the dataset so that rebuilding
    # can never silently mark anything as confirmed.
    ledger = {}
    if C.REVIEW_JSON.exists():
        ledger = json.loads(C.REVIEW_JSON.read_text()).get("verified", {})

    for o in observations:
        o["day"] = _day_index(o["collected"], first_day) if first_day else None
        o["kind"] = "quantity"
        o["text"] = None
        prov = o.setdefault("provenance", {})
        prov["page"] = o["page"]
        prov["bbox"] = o.get("bbox")
        prov["ocr"] = o.get("ocr", {})
        prov["human_verified"] = f"{o['page']}:{o['analyte']}" in ledger

        # Display the unit the analyte is DEFINED with, not the one OCR read.
        # Wrapped units arrive mangled ("10^3/mm^" + "3" -> "10^3/mm* 3") and
        # letters get mauled ("cells/cumm" -> "cellsfcumm", "mmol/L" -> "mmolft").
        # The canonical unit is known from config, so showing the OCR'd one buys
        # nothing but noise. The raw read is kept for the audit trail.
        meta = C.ANALYTES.get(o["analyte"])
        if meta:
            printed = (o.get("unit") or "").strip()
            prov["unit_as_printed"] = printed
            o["unit"] = _display_unit(printed, meta["unit"], o, prov)

        if make_crops and o.get("bbox"):
            page = o["page"]
            image = C.PAGES / f"pg-{page:03d}.jpg"
            if page not in page_size_cache:
                geo = analyse_page(image, page)
                page_size_cache[page] = (geo.width, geo.height)
            pw, ph = page_size_cache[page]
            out = C.CROPS / f"p{page:03d}_{o['analyte']}.jpg"
            if out.exists() or crops.make_crop(image, o["bbox"], out, pw, ph):
                prov["crop"] = str(out.relative_to(C.REPO)).replace("\\", "/")
                # Embed the evidence for anything a reader is most likely to
                # want to check: flagged values, and every critical result.
                # Embedding all 395 would add roughly 6 MB of base64 to a 1 MB
                # page; the rest are served from /crops/ by run.py, and the
                # Validation tab falls back to the path when opened as a file.
                if o.get("needs_review") or o.get("critical"):
                    uri = crops.as_data_uri(out)
                    if uri:
                        prov["crop_data"] = uri

    # ---- scores, one set per DAY ----
    #
    # Not per sample. MELD needs bilirubin, INR, creatinine, sodium and albumin,
    # and those are drawn into different tubes at different times of day -- the
    # coagulation sample has no bilirubin in it, the biochemistry sample has no
    # INR. Scoring each sample in isolation produced exactly one complete MELD
    # in eight days, every other row reporting five missing inputs that had in
    # fact been measured hours apart.
    #
    # A daily score is also what a ward round actually uses. Within a day the
    # latest value of each analyte wins, so a repeat supersedes the earlier draw.
    by_day: dict[str, dict[str, float]] = {}
    day_latest_time: dict[str, str] = {}
    seen_at: dict[str, tuple[str, float]] = {}      # analyte -> (day, value)

    for collected in sorted(by_sample):
        day = collected[:10]
        slot = by_day.setdefault(day, {})
        for o in by_sample[collected]:
            if o.get("value") is not None:
                slot[o["analyte"]] = o["value"]
                seen_at[o["analyte"]] = (day, o["value"])
        day_latest_time[day] = collected

    # Carry forward the most recent earlier value, up to CARRY_FORWARD_DAYS old.
    #
    # Not every analyte is drawn every day: bilirubin appears on 4 of 8 days,
    # INR on 5. Scoring only days where everything happened to be drawn leaves
    # most days blank, which is less informative than what a ward round actually
    # does -- it uses the last available result. Anything carried is named in
    # `carried_forward` on the row so the number is never quietly stale.
    from datetime import date as _date
    CARRY_FORWARD_DAYS = 2
    SCORE_INPUTS = ("bilirubin_total", "inr", "creatinine", "sodium", "albumin", "lactate")

    score_rows = []
    for day in sorted(by_day):
        vals = dict(by_day[day])
        carried = {}
        for analyte in SCORE_INPUTS:
            if vals.get(analyte) is not None:
                continue
            best_day, best_val = None, None
            for other_day in sorted(by_day):
                if other_day >= day:
                    break
                v = by_day[other_day].get(analyte)
                if v is not None:
                    best_day, best_val = other_day, v
            if best_day is None:
                continue
            age = (_date.fromisoformat(day) - _date.fromisoformat(best_day)).days
            if age <= CARRY_FORWARD_DAYS:
                vals[analyte] = best_val
                carried[analyte] = {"from": best_day, "days_old": age}

        collected = day_latest_time[day]
        row = {
            "collected": collected,
            "date": day,
            "day": _day_index(collected, first_day) if first_day else None,
            "carried_forward": carried,
            # dialysis and sex are clinical facts, not lab results. Sex is
            # printed on every page of this report ("36 years/Male") so it is
            # known. Dialysis is not recorded anywhere in the document.
            #
            # Passing None would mark every MELD 3.0 incomplete and the score
            # would never appear, which is not more honest -- it is just less
            # useful. Passing False silently would understate the score of a
            # dialysed patient by ~10 points. So: assume no renal replacement,
            # and say so on the result, where the doctor view shows it.
            "meld3": dict(scores.meld3(
                bilirubin=vals.get("bilirubin_total"), inr=vals.get("inr"),
                creatinine=vals.get("creatinine"), sodium=vals.get("sodium"),
                albumin=vals.get("albumin"), female=False, dialysis=False),
                assumptions=["no renal replacement therapy in the prior week "
                             "(not recorded in the lab data; confirm clinically)"]),
            "meld_na": scores.meld_na(
                bilirubin=vals.get("bilirubin_total"), inr=vals.get("inr"),
                creatinine=vals.get("creatinine"), sodium=vals.get("sodium")),
            "child_pugh": scores.child_pugh(
                bilirubin=vals.get("bilirubin_total"), albumin=vals.get("albumin"),
                inr=vals.get("inr"), ascites=None, encephalopathy=None),
            "aarc": scores.aarc(
                bilirubin=vals.get("bilirubin_total"), creatinine=vals.get("creatinine"),
                inr=vals.get("inr"), lactate=vals.get("lactate"), encephalopathy=None),
        }
        score_rows.append(row)

    found = patterns.find_patterns(observations, scores=score_rows)
    multivariate = build_multivariate(observations, days)

    # Formulas for the Formulas tab, straight from the scoring module's own
    # documentation so the equation shown to a clinician is the equation the
    # code runs. A test asserts the two cannot drift apart.
    formula_cards = build_formula_cards(score_rows[-1] if score_rows else {})

    return {
        # Demographics come from the dataset, never from the source. Hard-coding
        # them here put a real patient's age and sex into a committed source
        # file, where no privacy scan of data/ would ever look for it.
        "patient": raw.get("patient") or {"sex": C.PATIENT_SEX},
        "generated_from": {"pages": raw["coverage"]["pages"]},
        "days": days,
        "samples": raw["samples"],
        "observations": observations,
        "scores": score_rows,
        "formulas": formula_cards,
        "glossary": build_glossary(observations),
        "multivariate": multivariate,
        "analytics": build_analytics(observations, days, multivariate),
        "patterns": found,
        "coverage": raw["coverage"],
    }


def check_verification(dataset: dict, strict: bool) -> list[dict]:
    """Values that reach a chart but have not been confirmed by a human.

    Charted means: a quantity with a value and a day. Everything else is
    reference material.
    """
    pending = [o for o in dataset["observations"]
               if o.get("value") is not None
               and not o.get("provenance", {}).get("human_verified")]
    if strict and pending:
        raise SystemExit(
            f"BUILD BLOCKED: {len(pending)} charted values are not human-verified.\n"
            "Run  python run.py review  to work through them, or pass --no-strict\n"
            "to build a clearly-marked provisional dashboard."
        )
    return pending


def render(dataset: dict, provisional: bool) -> str:
    meta = {
        "provisional": provisional,
        "unverified": sum(1 for o in dataset["observations"]
                          if o.get("value") is not None
                          and not o["provenance"].get("human_verified")),
        "total_values": sum(1 for o in dataset["observations"] if o.get("value") is not None),
    }
    tabs = DA.all_tabs(dataset)
    return DA.page_shell("Liver report", tabs, json.dumps(dataset), meta)


def render_only(strict: bool = False) -> int:
    """Render the dashboard from an existing dataset, skipping extraction.

    A dataset need not come from OCR: the synthetic demo is written straight to
    labs.json. Even with a real document, re-running a twenty-minute extraction
    merely to redraw a chart is waste.
    """
    if not C.LABS_JSON.exists():
        raise SystemExit(
            f"No dataset at {C.LABS_JSON}.\n"
            "  python tools/make_synthetic.py   builds the synthetic demo dataset\n"
            "  python run.py                    processes a real document locally"
        )
    dataset = json.loads(C.LABS_JSON.read_text(encoding="utf-8"))
    pending = check_verification(dataset, strict)

    C.DIST.mkdir(parents=True, exist_ok=True)
    C.DASHBOARD.write_text(render(dataset, provisional=bool(pending)), encoding="utf-8")

    print(f"source       : {C.LABS_JSON.name}"
          f"{'  (SYNTHETIC)' if dataset.get('synthetic') else ''}")
    print(f"observations : {len(dataset.get('observations', []))}")
    print(f"written      : {C.DASHBOARD}")
    return 0


def main(strict: bool = False, make_crops: bool = True) -> int:
    raw_path = C.DATA / "raw_observations.json"
    if not raw_path.exists():
        # No extraction output: render whatever dataset is present. This is the
        # path the synthetic demo and CI take.
        return render_only(strict=strict)
    raw = json.loads(raw_path.read_text())
    dataset = assemble(raw, make_crops=make_crops)

    pending = check_verification(dataset, strict)
    C.LABS_JSON.write_text(json.dumps(dataset, indent=1))

    C.DIST.mkdir(parents=True, exist_ok=True)
    C.DASHBOARD.write_text(render(dataset, provisional=bool(pending)), encoding="utf-8")

    print(f"observations : {len(dataset['observations'])}")
    print(f"days         : {dataset['days']}")
    print(f"scores       : {len(dataset['scores'])}")
    print(f"patterns     : {len(dataset['patterns'])}")
    print(f"unverified   : {len(pending)}")
    print(f"written      : {C.DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
