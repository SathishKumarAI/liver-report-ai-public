"""Reference-range components: where a value sits, shown the same way everywhere.

A lab number on its own is not interpretable. "Creatinine 2.58" means nothing
without "normal is 0.67 to 1.17" beside it, and a reader asked to hold sixty
reference ranges in their head will not judge anything correctly.

So the range travels with the value, in one consistent form, in every place a
value appears: tiles, tables, charts, tooltips.

The hard part is scale. This dataset routinely runs an order of magnitude
outside normal -- bilirubin at fourteen times its ceiling -- so a linear gauge
puts the marker off the end of every bar and tells the reader nothing except
"far". The gauge therefore compresses the out-of-range region logarithmically
and SAYS SO, because a compressed axis that looks linear is a lie about
magnitude, and misleading a family about how abnormal a number is would be
worse than showing no gauge at all.
"""

from __future__ import annotations

import math

from . import config as C

# FHIR interpretation code -> (glyph, word, css class). Shape and word carry the
# meaning; colour only reinforces it. Greyscale printing and colour-blind
# readers get the same information.
BADGES = {
    "HH": ("▲▲", "critically high", "crit"),
    "H": ("▲", "high", "high"),
    "N": ("●", "normal", "ok"),
    "L": ("▼", "low", "low"),
    "LL": ("▼▼", "critically low", "crit"),
}


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _g(v) -> str:
    return f"{v:g}"


def range_badge(interpretation: str | None) -> str:
    """The H/L badge, identical everywhere it appears."""
    glyph, word, cls = BADGES.get(interpretation or "", ("", "", ""))
    if not glyph:
        return ""
    return (f'<span class="rbadge r-{cls}" title="{word}">'
            f'<span aria-hidden="true">{glyph}</span>'
            f'<span class="vh">{word}</span>'
            f'{_esc(interpretation)}</span>')


def range_label(ref: dict | None) -> str:
    """The range itself, in words. Handles one-sided and missing ranges."""
    ref = ref or {}
    lo, hi = ref.get("low"), ref.get("high")
    if lo is not None and hi is not None:
        return f"normal {_g(lo)}–{_g(hi)}"
    if hi is not None:
        return f"normal under {_g(hi)}"
    if lo is not None:
        return f"normal above {_g(lo)}"
    return "no printed range"


def fold_outside(value, ref: dict | None) -> float | None:
    """How many times outside its range a value sits. 1.0 means inside."""
    ref = ref or {}
    lo, hi = ref.get("low"), ref.get("high")
    if value is None or lo is None and hi is None:
        return None
    if hi is not None and hi > 0 and value > hi:
        return value / hi
    if lo is not None and value > 0 and value < lo:
        return lo / value
    return 1.0


def range_text(value, ref: dict | None, unit: str = "") -> str:
    """One plain sentence a non-medical reader can act on."""
    ref = ref or {}
    lo, hi = ref.get("low"), ref.get("high")
    unit = f" {unit}" if unit and unit.strip() else ""
    if value is None:
        return "not measured"
    if lo is None and hi is None:
        return f"{_g(value)}{unit}. The report prints no normal range for this test."

    fold = fold_outside(value, ref) or 1.0
    where = range_label(ref)

    if fold <= 1.0:
        # Inside the range: say where inside, because "normal" is not one point.
        if lo is not None and hi is not None and hi > lo:
            frac = (value - lo) / (hi - lo)
            spot = ("near the lower end" if frac < 0.25 else
                    "near the upper end" if frac > 0.75 else "mid-range")
            return f"{_g(value)}{unit} — inside normal, {spot} ({where})."
        return f"{_g(value)}{unit} — inside normal ({where})."

    high_side = hi is not None and value > hi
    if fold < 1.15:
        return (f"{_g(value)}{unit} — just "
                f"{'above' if high_side else 'below'} normal ({where}).")

    if high_side:
        return f"{_g(value)}{unit} — {fold:.1f} times the upper limit of normal ({where})."

    # Low values are NOT described as a multiple. "1.3 times the bottom of
    # normal" reads as high to anyone without a clinical background, which is
    # exactly the reader this sentence is written for. Say how far short it
    # falls instead.
    severity = "well below" if fold >= 1.5 else "below"
    short_by = f", short of {_g(lo)} by {_g(round(lo - value, 3))}" if lo is not None else ""
    return f"{_g(value)}{unit} — {severity} normal{short_by} ({where})."


def tooltip_text(obs: dict) -> str:
    """Everything a reader needs on hover, in plain words."""
    ref = obs.get("reference") or {}
    bits = [range_text(obs.get("value"), ref, obs.get("unit", ""))]
    when = (obs.get("collected") or "")[:16].replace("T", " ")
    if when:
        bits.append(f"Collected {when}.")
    if obs.get("critical"):
        bits.append("The laboratory flagged this as a critical result.")
    page = (obs.get("provenance") or {}).get("page")
    if page:
        bits.append(f"Read from page {page} of the report.")
    return " ".join(bits)


def range_gauge(value, ref: dict | None, unit: str = "",
                width: int = 190, compact: bool = False) -> str:
    """Where this value sits relative to its normal range.

    Layout: the normal band occupies the middle 40% of the track, and everything
    outside it is compressed logarithmically. One range-width outside normal is
    NOT the same distance as ten, and the axis says "log" so nobody reads the
    marker position as a linear magnitude.
    """
    ref = ref or {}
    lo, hi = ref.get("low"), ref.get("high")
    if value is None or (lo is None and hi is None):
        return ('<span class="gauge-none tiny">no printed range</span>'
                if not compact else "")

    h = 12 if compact else 20
    band_start, band_end = 0.30 * width, 0.70 * width

    def position(v: float) -> float:
        """Map a value onto the track. Inside the band it is linear; outside it
        is log-compressed so a 14x excursion still lands on the chart."""
        if lo is not None and hi is not None and lo <= v <= hi and hi > lo:
            return band_start + (band_end - band_start) * (v - lo) / (hi - lo)
        if hi is not None and v > hi:
            # log2 of the fold, saturating at 16x for the last 30% of the track.
            fold = max(1.0, v / hi) if hi > 0 else 1.0
            t = min(1.0, math.log2(fold) / 4.0)
            return band_end + (width - band_end) * t
        if lo is not None and v < lo:
            fold = max(1.0, lo / v) if v > 0 else 16.0
            t = min(1.0, math.log2(fold) / 4.0)
            return band_start - band_start * t
        # One-sided range and the value is on the unbounded side.
        return band_start if hi is None else band_end

    x = position(float(value))
    fold = fold_outside(value, ref) or 1.0
    inside = fold <= 1.0
    cls = "in" if inside else ("hi" if (hi is not None and value > hi) else "lo")

    band = (f'<rect x="{band_start:.1f}" y="0" width="{band_end - band_start:.1f}" '
            f'height="{h}" rx="3" class="gz-band"/>')
    track = f'<rect x="0" y="0" width="{width}" height="{h}" rx="3" class="gz-track"/>'
    mark = (f'<rect x="{max(0.0, min(width - 3, x - 1.5)):.1f}" y="-2" width="3" '
            f'height="{h + 4}" rx="1.5" class="gz-mark gz-{cls}"/>')

    label = range_text(value, ref, unit)
    svg = (f'<svg class="gauge" viewBox="-2 -3 {width + 4} {h + 6}" '
           f'role="img" aria-label="{_esc(label)}">{track}{band}{mark}</svg>')

    if compact:
        return f'<span class="gauge-wrap compact" title="{_esc(label)}">{svg}</span>'

    bounds = (f'<span class="gz-lo">{_g(lo) if lo is not None else ""}</span>'
              f'<span class="gz-note">{_esc(range_label(ref))}'
              f'{" · outside normal shown on a log scale" if not inside else ""}'
              f'</span>'
              f'<span class="gz-hi">{_g(hi) if hi is not None else ""}</span>')
    return (f'<span class="gauge-wrap" title="{_esc(label)}">{svg}'
            f'<span class="gz-bounds">{bounds}</span></span>')


CSS = """
/* Reference-range components. Status is glyph + letter + colour, never colour
   alone, so greyscale printing and colour-blind readers lose nothing. */
.rbadge{display:inline-flex;align-items:center;gap:3px;font-size:var(--fs-micro);
 font-weight:700;padding:1px 6px;border-radius:999px;border:1px solid currentColor;
 line-height:1.5;white-space:nowrap}
.r-high{color:var(--high)} .r-low{color:var(--low)}
.r-crit{color:var(--crit)} .r-ok{color:var(--subtext);font-weight:600}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
 clip-path:inset(50%);white-space:nowrap}
.gauge-wrap{display:inline-block;max-width:100%}
.gauge{display:block;width:100%;height:auto;overflow:visible}
.gauge-wrap.compact{width:74px;vertical-align:middle}
.gz-track{fill:var(--surface)}
.gz-band{fill:var(--ok-band,var(--accent));opacity:.20}
.gz-mark{fill:var(--text)}
.gz-mark.gz-hi{fill:var(--high)} .gz-mark.gz-lo{fill:var(--low)}
.gz-mark.gz-in{fill:var(--subtext)}
.gz-bounds{display:flex;justify-content:space-between;gap:6px;
 font-size:var(--fs-micro);color:var(--faint);margin-top:2px}
.gz-note{flex:1;text-align:center}
.gauge-none{color:var(--faint)}
"""


if __name__ == "__main__":
    import json
    from pathlib import Path

    cases = [
        ("bilirubin far out", 18.0, {"low": 0.3, "high": 1.2}, "mg/dL"),
        ("inside range", 4.1, {"low": 3.5, "high": 5.1}, "mEq/L"),
        ("near lower end", 3.6, {"low": 3.5, "high": 5.1}, "mEq/L"),
        ("below range", 2.7, {"low": 3.5, "high": 5.2}, "g/dL"),
        ("one-sided high", 4.11, {"low": None, "high": 0.5}, "ng/mL"),
        ("no range at all", 12.0, {"low": None, "high": None}, "Seconds"),
        ("exactly on bound", 1.2, {"low": 0.3, "high": 1.2}, "mg/dL"),
    ]

    def interp_of(value, ref) -> str | None:
        """Same rule the pipeline uses, so the preview cannot disagree with it."""
        lo, hi = (ref or {}).get("low"), (ref or {}).get("high")
        if lo is None and hi is None:
            return None
        if hi is not None and value > hi:
            return "H"
        if lo is not None and value < lo:
            return "L"
        return "N"

    rows = []
    for name, value, ref, unit in cases:
        rows.append(
            f"<tr><td>{name}</td><td>{range_badge(interp_of(value, ref))}</td>"
            f"<td style='width:230px'>{range_gauge(value, ref, unit)}</td>"
            f"<td>{range_gauge(value, ref, unit, compact=True)}</td>"
            f"<td class='t'>{_esc(range_text(value, ref, unit))}</td></tr>")
        print(f"{name:20} {range_text(value, ref, unit)}")

    page = ("<!doctype html><meta charset=utf-8><title>range components</title>"
            "<style>:root{--fs-micro:11px;--surface:#313244;--accent:#a6e3a1;"
            "--text:#cdd6f4;--subtext:#a6adc8;--faint:#7f849c;--high:#fab387;"
            "--low:#89b4fa;--crit:#f38ba8}"
            "body{background:#1e1e2e;color:#cdd6f4;font:14px system-ui;padding:22px}"
            "table{border-collapse:collapse;width:100%}td{padding:10px 8px;"
            "border-bottom:1px solid #313244;vertical-align:middle}"
            ".t{color:#a6adc8;font-size:13px}</style>"
            f"<style>{CSS}</style><table>{''.join(rows)}</table>")

    out = Path(__file__).resolve().parent.parent / "dist" / "_range_preview.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")

    assert "http" not in CSS
    assert "no printed range" in range_gauge(5, {"low": None, "high": None})
    assert range_badge(None) == ""
    assert "critically high" in range_badge("HH")
    print(f"\nwrote {out}")
    print("OK")
