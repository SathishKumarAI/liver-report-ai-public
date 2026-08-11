"""Chart types the tab builders do not have, each answering a question the
existing sparkline-per-tile layout cannot.

Owns: five HTML-fragment builders (small multiples, day-vs-day comparison,
distribution strips, the dense matrix, the pairwise grid) and the CSS they need,
exported as CHART_CSS for the lead to append to dashboard_assets.CSS.

Does NOT own: the data, the page shell, the stylesheet, or any behaviour. Every
builder is a pure function of the parsed labs.json dict and returns a string.
Sorting and filtering hooks are emitted as data- attributes only; the wiring
belongs to the interaction agent.

The rule every chart here obeys, because it is what the reader asked for:
**the normal range is drawn or printed on every single chart**, and status is
carried by shape and letter as well as colour, so it survives a greyscale ward
printer and a colour-blind reader.

Adding an analyte to the pairwise grid -> CORR_KEYS below. Adding a chart ->
also add its CSS block to CHART_CSS; nothing here reaches for a stylesheet it
does not ship.
"""

from __future__ import annotations

import statistics

from . import config as C
from .dashboard_assets import (
    _esc, _group_keys, _isnum, _label, _num, _ref, _series, _unit,
    band_text, flag_badge, spark_block,
)

# ponytail: src/dashboard_range.py did not exist when this was written, so the
# value-to-position mapping below (_win/_px) is local. It is ~8 lines and is the
# only overlap; delete it and import from that module once it lands.


def _empty(msg: str) -> str:
    return f'<p class="empty">{_esc(msg)}</p>'


def _win(vals, lo, hi, pad=0.06):
    """Axis window that always contains the reference range AND the data.

    Unlike the tile sparkline (which zooms to the data and clips the band),
    every chart in this module is *about* the distance from normal, so the band
    must stay on screen even when the data is twenty times above it.
    """
    pts = [v for v in vals if _isnum(v)] + [x for x in (lo, hi) if _isnum(x)]
    if not pts:
        return 0.0, 1.0
    a, b = min(pts), max(pts)
    if b == a:
        b = a + max(abs(a) * 0.1, 0.5)
    m = (b - a) * pad
    return a - m, b + m


def _px(v, a, b, left, right):
    return round(left + (v - a) / (b - a) * (right - left), 1)


def _day_values(ser: dict, days: list) -> dict:
    """analyte -> {ISO day: value}. Several samples share a day; the last
    numeric reading of the day wins, because that is the one the ward acted on."""
    out: dict = {}
    for k, obs in ser.items():
        by: dict = {}
        for o in obs:
            v = o.get("value")
            if _isnum(v) and o.get("collected"):
                by[o["collected"][:10]] = v
        if by:
            out[k] = by
    return out


def _flag_at(obs, day):
    for o in reversed(obs):
        if (o.get("collected") or "")[:10] == day and _isnum(o.get("value")):
            return o.get("interpretation")
    return None


def _cell_cls(v, lo, hi, interp) -> str:
    if interp in ("HH", "LL"):
        return "crit"
    if _isnum(hi) and _isnum(v) and v > hi:
        return "hi"
    if _isnum(lo) and _isnum(v) and v < lo:
        return "lo"
    return "ok"


def _mark(interp) -> str:
    """Glyph + letter for a table cell: readable with no colour at all."""
    if not interp or interp == "N":
        return ""
    glyph = C and FLAG_GLYPH.get(interp, "◆")
    return f'<span class="gm"><span aria-hidden="true">{glyph}</span>{_esc(interp)}</span>'


FLAG_GLYPH = {"HH": "▲▲", "H": "▲", "LL": "▼▼", "L": "▼", "A": "◆"}

_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _short_day(iso: str) -> str:
    try:
        y, m, dd = iso.split("-")
        return f"{int(dd)} {_MON[int(m) - 1]}"
    except Exception:
        return iso


def _groups_present(ser: dict) -> list:
    return [(g, t) for g, t in C.GROUPS.items() if _group_keys(ser, g)]


# --------------------------------------------------------------------------
# 1. Small multiples -- everything at once, each with its own normal range.
# --------------------------------------------------------------------------
def small_multiples(d: dict, group=None) -> str:
    """A mini chart per analyte, sectioned by body system.

    Reuses the tile sparkline rather than growing a second chart engine: it
    already draws the band, marks out-of-range points as triangles, and captions
    the range in words. What this adds is the grid, the called-out latest value
    and an honest note when the zoom has pushed the band off the chart.
    """
    ser = _series(d)
    if not ser:
        return _empty("No observations to chart.")
    wanted = [(g, t) for g, t in _groups_present(ser) if group in (None, g)]
    if not wanted:
        return _empty("No analytes in that group.")

    out = []
    for g, title in wanted:
        cells = []
        for k in _group_keys(ser, g):
            obs = ser[k]
            vals = [o.get("value") for o in obs]
            nums = [v for v in vals if _isnum(v)]
            if not nums:
                continue
            lo, hi = _ref(obs)
            last = [o for o in obs if _isnum(o.get("value"))][-1]
            off = ""
            if _isnum(hi) and min(nums) > hi:
                off = "chart is zoomed above the normal range"
            elif _isnum(lo) and max(nums) < lo:
                off = "chart is zoomed below the normal range"
            cells.append(
                f'<figure class="sm" data-analyte="{_esc(k)}" data-group="{_esc(g)}">'
                f'<figcaption class="smhead"><span class="smlab">{_esc(_label(k))}</span>'
                f'{flag_badge(last.get("interpretation"))}</figcaption>'
                f'<p class="smval">{_num(last.get("value"))}'
                f'<span class="smunit">{_esc(_unit(k))}</span></p>'
                + spark_block(vals, lo, hi)
                + (f'<p class="smoff">{_esc(off)}</p>' if off else "")
                + "</figure>")
        if cells:
            out.append(f'<h3 class="eyebrow">{_esc(title)}</h3>'
                       f'<div class="smgrid">{"".join(cells)}</div>')
    if not out:
        return _empty("No numeric results to chart.")
    return ('<p class="sub">Every test, drawn to the same rules. The shaded band '
            'is the normal range; a triangle marks a reading outside it. Each '
            'chart is scaled to its own numbers, so the range in words under the '
            'chart is the one to read.</p>' + "".join(out))


# --------------------------------------------------------------------------
# 2. Two days, side by side.
# --------------------------------------------------------------------------
def compare_days(d: dict, day_a: str | None = None, day_b: str | None = None) -> str:
    """Every analyte measured on both days: A, B, change, % and normal range.

    Sorted by change measured in normal-range widths, not by percent. Percent
    alone puts base excess (0.1 -> -3.0, "-3100%") above bilirubin, which is
    noise dressed as the headline; the range width is the unit a clinician
    already thinks in, and it is comparable across tests.
    """
    days = list(d.get("days") or [])
    ser = _series(d)
    if len(days) < 2 or not ser:
        return _empty("Two days of results are needed to compare.")
    a = day_a if day_a in days else days[0]
    b = day_b if day_b in days else days[-1]
    dv = _day_values(ser, days)

    rows = []
    for k, by in dv.items():
        if a not in by or b not in by:
            continue
        va, vb = by[a], by[b]
        lo, hi = _ref(ser[k])
        delta = vb - va
        pct = (delta / va * 100) if va else None
        width = (hi - lo) if (_isnum(lo) and _isnum(hi) and hi > lo) else (
            abs(hi) if _isnum(hi) and hi else (abs(va) or 1.0))
        rows.append((abs(delta) / width, k, va, vb, delta, pct, lo, hi))
    if not rows:
        return _empty(f"Nothing was measured on both {_short_day(a)} and {_short_day(b)}.")
    rows.sort(reverse=True)

    def pick(side, sel):
        opts = "".join(f'<option value="{_esc(x)}"{" selected" if x == sel else ""}>'
                       f'{_esc(_short_day(x))}</option>' for x in days)
        return (f'<label class="cmppick">Day {side.upper()}'
                f'<select data-cmp="{side}">{opts}</select></label>')

    tr = []
    for mag, k, va, vb, delta, pct, lo, hi in rows:
        fa, fb = _flag_at(ser[k], a), _flag_at(ser[k], b)
        worse = ((k in C.WORSE_WHEN_RISING and delta > 0)
                 or (k in C.WORSE_WHEN_FALLING and delta < 0))
        better = ((k in C.WORSE_WHEN_RISING and delta < 0)
                  or (k in C.WORSE_WHEN_FALLING and delta > 0))
        word = "worse" if worse else ("better" if better else "changed")
        if abs(delta) < 1e-9:
            arrow, word = "→", "unchanged"
        else:
            arrow = "↑" if delta > 0 else "↓"
        tr.append(
            f'<tr data-analyte="{_esc(k)}" data-group="{_esc(C.ANALYTES.get(k, {}).get("group", ""))}"'
            f' data-mag="{mag:.4f}">'
            f'<th scope="row">{_esc(_label(k))}<span class="u">{_esc(_unit(k))}</span></th>'
            f'<td class="n" data-day="{_esc(a)}">{_num(va)} {_mark(fa)}</td>'
            f'<td class="n" data-day="{_esc(b)}">{_num(vb)} {_mark(fb)}</td>'
            f'<td class="n"><span class="cmpdir cmp-{word}">'
            f'<span aria-hidden="true">{arrow}</span> {"+" if delta > 0 else ""}'
            f'{_num(round(delta, 4))}</span></td>'
            f'<td class="n">{"—" if pct is None else f"{pct:+.0f}%"}</td>'
            f'<td class="n">{_esc(word)}</td>'
            f'<td class="rng">{_esc(band_text(lo, hi))}</td></tr>')

    return (f'<div class="cmpbar">{pick("a", a)}{pick("b", b)}'
            f'<span class="tiny">{len(rows)} tests measured on both days</span></div>'
            '<div class="scroll"><table class="cmp" id="cmp-table">'
            f'<caption class="tiny">Every test with a result on both '
            f'{_esc(_short_day(a))} and {_esc(_short_day(b))}, biggest movement first. '
            'Movement is measured in normal-range widths so that tests with very '
            'different scales can be ranked against each other. Where the day holds '
            'more than one sample, the last one of that day is shown.</caption>'
            '<thead><tr><th scope="col" data-key="label">Test</th>'
            f'<th scope="col" class="n" data-key="a">{_esc(_short_day(a))}</th>'
            f'<th scope="col" class="n" data-key="b">{_esc(_short_day(b))}</th>'
            '<th scope="col" class="n" data-key="delta">Change</th>'
            '<th scope="col" class="n" data-key="pct">%</th>'
            '<th scope="col" class="n" data-key="word">Direction</th>'
            '<th scope="col" data-key="range">Normal range</th></tr></thead>'
            f'<tbody>{"".join(tr)}</tbody></table></div>')


# --------------------------------------------------------------------------
# 3. Distribution strips -- spread and centre against the range.
# --------------------------------------------------------------------------
def _strip_svg(vals, lo, hi, w=480, h=20) -> str:
    a, b = _win(vals, lo, hi)
    left, right, mid = 4.0, w - 4.0, h / 2
    out = []
    if _isnum(lo) or _isnum(hi):
        x1 = _px(lo, a, b, left, right) if _isnum(lo) else left
        x2 = _px(hi, a, b, left, right) if _isnum(hi) else right
        out.append(f'<rect class="ds-band" x="{x1}" y="3" '
                   f'width="{max(round(x2 - x1, 1), 2)}" height="{h - 6}"/>')
        for lim in (lo, hi):
            if _isnum(lim):
                x = _px(lim, a, b, left, right)
                out.append(f'<line class="ds-lim" x1="{x}" x2="{x}" y1="1" y2="{h - 1}"/>')
    nums = [v for v in vals if _isnum(v)]
    med = statistics.median(nums)
    xm = _px(med, a, b, left, right)
    out.append(f'<line class="ds-med" x1="{xm}" x2="{xm}" y1="1.5" y2="{h - 1.5}"/>')
    last = nums[-1]
    for i, v in enumerate(nums):
        x, now = _px(v, a, b, left, right), i == len(nums) - 1
        r = 3.4 if now else 2.4
        if now:
            out.append(f'<circle class="ds-halo" cx="{x}" cy="{mid}" r="{r + 2.4}"/>')
        if _isnum(hi) and v > hi:
            s = r * 1.25
            out.append(f'<path class="ds-out{" now" if now else ""}" '
                       f'd="M{x} {mid - s * 1.1}l{s} {s * 1.9}h{-2 * s}z"/>')
        elif _isnum(lo) and v < lo:
            s = r * 1.25
            out.append(f'<path class="ds-out{" now" if now else ""}" '
                       f'd="M{x} {mid + s * 1.1}l{s} {-s * 1.9}h{-2 * s}z"/>')
        else:
            out.append(f'<circle class="ds-pt{" now" if now else ""}" cx="{x}" '
                       f'cy="{mid}" r="{r}"/>')
    return (f'<svg class="ds" viewBox="0 0 {w} {h}" role="img" aria-label="'
            f'{len(nums)} readings from {_num(min(nums))} to {_num(max(nums))}, '
            f'median {_num(round(med, 4))}, latest {_num(last)}, '
            f'{_esc(band_text(lo, hi))}">' + "".join(out) + "</svg>")


def distribution_strip(d: dict) -> str:
    """One strip per analyte: every reading placed against its normal range.

    The axis always contains the range, so a strip whose points all sit hard
    right of the band says "far above normal" without the reader doing arithmetic.
    """
    ser = _series(d)
    if not ser:
        return _empty("No observations to chart.")
    out, singles = [], []
    for g, title in _groups_present(ser):
        rows = []
        for k in _group_keys(ser, g):
            obs = ser[k]
            vals = [o.get("value") for o in obs]
            nums = [v for v in vals if _isnum(v)]
            if not nums:
                continue
            if len(nums) < 2:
                singles.append(_label(k))
                continue
            lo, hi = _ref(obs)
            last = [o for o in obs if _isnum(o.get("value"))][-1]
            rows.append(
                f'<li class="dsrow" data-analyte="{_esc(k)}" data-group="{_esc(g)}">'
                f'<span class="dslab">{_esc(_label(k))}'
                f'<span class="u">{_esc(_unit(k))}</span></span>'
                + _strip_svg(vals, lo, hi)
                + f'<span class="dsmeta">{_esc(band_text(lo, hi))} · '
                  f'{len(nums)} readings {_num(min(nums))}–{_num(max(nums))} · '
                  f'median {_num(round(statistics.median(nums), 4))} · latest '
                  f'<b>{_num(last.get("value"))}</b> '
                  f'{flag_badge(last.get("interpretation"))}</span></li>')
        if rows:
            out.append(f'<h3 class="eyebrow">{_esc(title)}</h3>'
                       f'<ul class="dslist">{"".join(rows)}</ul>')
    if not out:
        return _empty("No analyte has enough readings to show a spread.")
    tail = ""
    if singles:
        tail = (f'<p class="tiny">{len(singles)} tests were measured only once, so '
                'they have no spread to show: ' + _esc(", ".join(sorted(singles))) + ".</p>")
    return ('<p class="sub">Each strip is one test. The shaded block is its normal '
            'range, the tall line is the middle reading, the ringed mark is the '
            'latest, and a triangle means that reading sat outside the range. '
            'The scale always includes the normal range, so distance from the '
            'block is distance from normal.</p>'
            '<p class="dskey"><span class="k"><svg class="dskeysw" viewBox="0 0 30 14" '
            'aria-hidden="true"><rect class="ds-band" x="0" y="2" width="30" height="10"/>'
            '</svg>normal range</span>'
            '<span class="k"><svg class="dskeysw" viewBox="0 0 14 14" aria-hidden="true">'
            '<line class="ds-med" x1="7" x2="7" y1="1" y2="13"/></svg>median</span>'
            '<span class="k"><svg class="dskeysw" viewBox="0 0 14 14" aria-hidden="true">'
            '<circle class="ds-halo" cx="7" cy="7" r="6"/>'
            '<circle class="ds-pt now" cx="7" cy="7" r="3.4"/></svg>latest</span>'
            '<span class="k"><svg class="dskeysw" viewBox="0 0 14 14" aria-hidden="true">'
            '<path class="ds-out" d="M7 3l4 8h-8z"/></svg>outside the range</span></p>'
            + "".join(out) + tail)


# --------------------------------------------------------------------------
# 4. The dense matrix -- analytes down, days across, range pinned.
# --------------------------------------------------------------------------
def matrix_table(d: dict) -> str:
    """Every analyte against every day, with the normal range as a fixed column.

    Emits the sort/filter contract as data- attributes and nothing else:
      table#matrix        data-days="ISO,ISO,..."
      thead th            data-key, aria-sort="none" on sortable columns
      tbody tr            data-analyte data-group data-label data-n data-out
                          data-latest data-mag  (mag = |last-first| in range widths)
      td.gc               data-day data-value data-flag, data-sort for numeric sort
    """
    days = list(d.get("days") or [])
    ser = _series(d)
    if not days or not ser:
        return _empty("No results to tabulate.")
    dv = _day_values(ser, days)

    body = []
    for g, _t in _groups_present(ser):
        for k in _group_keys(ser, g):
            by = dv.get(k)
            if not by:
                continue
            obs = ser[k]
            lo, hi = _ref(obs)
            nums = [o["value"] for o in obs if _isnum(o.get("value"))]
            first, last = nums[0], nums[-1]
            width = (hi - lo) if (_isnum(lo) and _isnum(hi) and hi > lo) else (
                abs(hi) if _isnum(hi) and hi else (abs(first) or 1.0))
            out_n = sum(1 for o in obs
                        if o.get("interpretation") in ("H", "L", "HH", "LL"))
            lastf = [o for o in obs if _isnum(o.get("value"))][-1]
            tds = []
            for day in days:
                v = by.get(day)
                if v is None:
                    tds.append(f'<td class="gc none" data-day="{_esc(day)}" '
                               'data-sort="" aria-label="not measured">·</td>')
                    continue
                f = _flag_at(obs, day)
                tds.append(
                    f'<td class="gc {_cell_cls(v, lo, hi, f)}" data-day="{_esc(day)}" '
                    f'data-value="{v}" data-sort="{v}" data-flag="{_esc(f or "")}">'
                    f'{_num(v)}{_mark(f)}</td>')
            body.append(
                f'<tr data-analyte="{_esc(k)}" data-group="{_esc(g)}" '
                f'data-label="{_esc(_label(k))}" data-n="{len(nums)}" '
                f'data-out="{out_n}" data-latest="{last}" '
                f'data-mag="{abs(last - first) / width:.4f}">'
                f'<th scope="row" class="mxname">{_esc(_label(k))}'
                f'<span class="u">{_esc(_unit(k))}</span></th>'
                f'<td class="mxsys" data-sort="{_esc(C.GROUPS.get(g, g))}">'
                f'{_esc(C.GROUPS.get(g, g))}</td>'
                f'<td class="rng" data-sort="{_esc(band_text(lo, hi))}">'
                f'{_esc(band_text(lo, hi))}</td>'
                + "".join(tds)
                + f'<td class="n" data-sort="{len(nums)}">{len(nums)}</td>'
                + f'<td class="n" data-sort="{out_n}">{out_n}</td>'
                + f'<td class="gc {_cell_cls(last, lo, hi, lastf.get("interpretation"))}"'
                  f' data-sort="{abs(last - first) / width:.4f}">{_num(last)}'
                  f'{_mark(lastf.get("interpretation"))}</td></tr>')

    ths = "".join(f'<th scope="col" class="n" data-key="{_esc(day)}" aria-sort="none">'
                  f'{_esc(_short_day(day))}</th>' for day in days)
    return ('<div class="scroll"><table class="mx flow" id="matrix" '
            f'data-days="{_esc(",".join(days))}">'
            '<caption class="tiny">Every test as a row, every day as a column, with '
            'the normal range kept beside the name so no cell has to be read from '
            'memory. A cell carries an arrow and a letter as well as a tint: '
            '▲ H above the range, ▼ L below it, doubled when critical, a dot where '
            'nothing was measured. Where a day holds several samples the last one '
            'is shown. Column headings are buttons once the page is interactive.'
            '</caption><thead><tr>'
            '<th scope="col" data-key="label" aria-sort="none">Test</th>'
            '<th scope="col" data-key="group" aria-sort="none">System</th>'
            '<th scope="col" data-key="range">Normal range</th>' + ths +
            '<th scope="col" class="n" data-key="n" aria-sort="none" '
            'title="how many readings">Readings</th>'
            '<th scope="col" class="n" data-key="out" aria-sort="none" '
            'title="readings outside the normal range">Outside</th>'
            '<th scope="col" class="n" data-key="mag" aria-sort="none" '
            'title="latest value; sorts by total movement in range widths">Latest</th>'
            f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


# --------------------------------------------------------------------------
# 5. Pairwise grid -- descriptive only, and it says so.
# --------------------------------------------------------------------------
CORR_KEYS = ["bilirubin_total", "inr", "pt", "creatinine", "urea", "ammonia",
             "platelets", "albumin", "sodium", "ast", "alt", "lactate",
             "crp", "procalcitonin"]
MIN_PAIR_DAYS = 4


def correlation_grid(d: dict) -> str:
    """How the key tests moved relative to each other, with the sample size on
    every cell and no inference attached.

    Eight days of one patient. There is no p-value here, no fitted line and no
    causal claim, because none of the three would be honest at n=8.
    """
    days = list(d.get("days") or [])
    ser = _series(d)
    if not days or not ser:
        return _empty("No results to compare.")
    dv = _day_values(ser, days)
    keys = [k for k in CORR_KEYS if len(dv.get(k, {})) >= MIN_PAIR_DAYS]
    if len(keys) < 2:
        return _empty("Not enough tests have four or more days of results.")

    rows = []
    for i, ky in enumerate(keys[1:], start=1):
        tds = []
        for kx in keys[:i]:
            common = [day for day in days if day in dv[kx] and day in dv[ky]]
            n = len(common)
            if n < MIN_PAIR_DAYS:
                tds.append(f'<td class="cc thin" data-n="{n}" '
                           f'title="only {n} days overlap — not shown">'
                           f'<span class="cn">n={n}</span></td>')
                continue
            xs = [dv[kx][day] for day in common]
            ys = [dv[ky][day] for day in common]
            try:
                r = statistics.correlation(xs, ys)
            except (statistics.StatisticsError, ValueError):
                tds.append(f'<td class="cc thin" data-n="{n}" '
                           'title="one of the two did not vary">'
                           f'<span class="cn">n={n}</span></td>')
                continue
            glyph = "⇈" if r >= 0.3 else ("⇅" if r <= -0.3 else "·")
            word = ("moved together" if r >= 0.3 else
                    "moved opposite" if r <= -0.3 else "no clear pattern")
            tint = round(min(abs(r), 1.0) * 26)
            tds.append(
                f'<td class="cc" data-x="{_esc(kx)}" data-y="{_esc(ky)}" '
                f'data-r="{r:.3f}" data-n="{n}" '
                f'style="background:color-mix(in srgb,var(--accent) {tint}%,var(--surface))" '
                f'title="{_esc(_label(kx))} and {_esc(_label(ky))}: {word} across '
                f'{n} days">'
                f'<span class="cg" aria-hidden="true">{glyph}</span>'
                f'<span class="cr">{r:+.2f}</span><span class="cn">n={n}</span></td>')
        tds += ['<td class="cc pad"></td>'] * (len(keys) - 1 - i)
        rows.append(f'<tr><th scope="row">{_esc(_label(ky))}</th>{"".join(tds)}</tr>')

    head = "".join(f'<th scope="col" class="ccol">{_esc(_label(k))}</th>'
                   for k in keys[:-1])
    return ('<p class="notice"><b>Read this as a description, not an explanation.</b> '
            'These are eight days from one person. Two tests moving together does '
            'not mean one caused the other — in a liver injury nearly everything '
            'moves at once, because the illness moved. No significance test is '
            'run, no p-value is shown and no line is fitted, because at this '
            'number of days none of those would mean anything.</p>'
            '<p class="sub">Each cell gives the direction the pair moved, a number '
            'between −1 and +1 for how tightly they tracked, and <b>n</b>, the '
            'number of days on which both were measured. '
            f'Pairs with fewer than {MIN_PAIR_DAYS} shared days are left blank.</p>'
            '<p class="dskey"><span class="k"><b aria-hidden="true">⇈</b> moved '
            'together</span><span class="k"><b aria-hidden="true">⇅</b> moved in '
            'opposite directions</span><span class="k"><b aria-hidden="true">·</b> '
            'no clear pattern</span></p>'
            '<div class="scroll"><table class="corr">'
            '<caption class="tiny">Pairwise movement among the tests with at least '
            f'{MIN_PAIR_DAYS} days of results. Lower triangle only: the mirror half '
            'would repeat every cell.</caption>'
            f'<thead><tr><td class="pad"></td>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# --------------------------------------------------------------------------
# CSS. Tokens only -- no literal colour appears below.
# --------------------------------------------------------------------------
CHART_CSS = """
/* ==== dashboard_charts.py: small multiples, compare, strips, matrix, pairs ==== */
.smgrid{display:grid;gap:var(--s3);margin-bottom:var(--s4);
 grid-template-columns:repeat(auto-fill,minmax(13.5rem,1fr))}
figure.sm{margin:0;background:var(--surface);border:1px solid var(--line);
 border-radius:var(--radius);padding:var(--s3);box-shadow:var(--shadow)}
figure.sm .smhead{display:flex;align-items:flex-start;justify-content:space-between;
 gap:var(--s2)}
figure.sm .smlab{font-size:var(--fs-tiny);font-weight:620;color:var(--dim);line-height:1.35}
figure.sm .smval{font-size:var(--fs-h2);font-weight:650;letter-spacing:-.02em;
 margin:var(--s1) 0 0;line-height:1.1;font-variant-numeric:tabular-nums}
figure.sm .smunit{font-size:var(--fs-micro);color:var(--dim);font-weight:500;
 margin-left:.3rem;letter-spacing:0}
figure.sm figure.sparkwrap{max-width:none}
figure.sm .smoff{margin:var(--s1) 0 0;font-size:var(--fs-micro);color:var(--faint)}

.cmpbar{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--s3);margin:var(--s3) 0}
.cmppick{display:inline-flex;align-items:center;gap:var(--s2);font-size:var(--fs-tiny);
 color:var(--dim)}
.cmppick select{background:var(--bg2);border:1px solid var(--line);border-radius:8px;
 color:inherit;font:inherit;font-size:var(--fs-tiny);padding:.3rem .5rem}
table.cmp{font-variant-numeric:tabular-nums}
table.cmp caption,table.mx caption,table.corr caption{text-align:left;color:var(--faint);
 padding-bottom:var(--s2);max-width:52rem;white-space:normal}
table.cmp th[scope=row]{font-weight:600;color:var(--text);white-space:normal;min-width:9rem}
table.cmp .u,table.mx .u{color:var(--faint);font-weight:400;font-size:var(--fs-micro);
 margin-left:.35rem}
table.cmp td.rng,table.mx td.rng{color:var(--dim);white-space:nowrap}
.cmpdir{font-weight:640;white-space:nowrap}
.cmp-worse{color:var(--high)}.cmp-better{color:var(--norm)}
.cmp-changed,.cmp-unchanged{color:var(--dim)}

ul.dslist{list-style:none;margin:0 0 var(--s4);padding:0;display:grid;gap:var(--s2)}
li.dsrow{display:grid;gap:0 var(--s3);align-items:center;
 grid-template-columns:minmax(8rem,11rem) minmax(0,1fr);
 padding:var(--s2) 0;border-bottom:1px solid var(--line)}
li.dsrow .dslab{font-size:var(--fs-tiny);font-weight:620;color:var(--dim);line-height:1.3}
svg.ds{width:100%;max-width:34rem;height:auto;display:block}
li.dsrow .dsmeta{grid-column:2;font-size:var(--fs-micro);color:var(--faint);
 font-variant-numeric:tabular-nums;padding-top:2px}
li.dsrow .dsmeta b{color:var(--text)}
.ds-band{fill:var(--band)}
.ds-lim{stroke:var(--faint);stroke-width:1;stroke-dasharray:2 3;opacity:.8;
 vector-effect:non-scaling-stroke}
.ds-med{stroke:var(--text);stroke-width:1.5;opacity:.75;vector-effect:non-scaling-stroke}
.ds-pt{fill:var(--faint)}
.ds-pt.now{fill:var(--accent)}
.ds-out{fill:var(--high)}
.ds-halo{fill:none;stroke:var(--accent);stroke-width:1.25;opacity:.6;
 vector-effect:non-scaling-stroke}
.dskey{display:flex;flex-wrap:wrap;gap:var(--s2) var(--s4);margin:0 0 var(--s4);
 font-size:var(--fs-micro);color:var(--dim)}
.dskey .k{display:inline-flex;align-items:center;gap:6px}
.dskey b{font-size:var(--fs-tiny);color:var(--text)}
svg.dskeysw{height:14px;width:auto;flex:none}

table.mx{font-variant-numeric:tabular-nums;border-collapse:separate;border-spacing:2px}
table.mx th[scope=col]{white-space:nowrap;padding:.3rem .5rem}
table.mx th.mxname{font-weight:600;color:var(--text);text-transform:none;
 letter-spacing:0;font-size:var(--fs-tiny);white-space:nowrap;background:var(--surface)}
table.mx td.mxsys{color:var(--dim);white-space:nowrap}
table.mx td.gc{min-width:3.6rem;text-align:right}
table.mx td.gc .gm{font-size:9px;font-weight:700;margin-left:3px;vertical-align:super;
 letter-spacing:.02em}
table.mx thead th{position:sticky;top:0;background:var(--bg2);z-index:2}
table.mx th.mxname{position:sticky;left:0;z-index:1}
table.mx thead th:first-child{z-index:3}

table.corr{border-collapse:separate;border-spacing:2px;font-variant-numeric:tabular-nums}
table.corr th{font-weight:600;color:var(--dim);text-transform:none;letter-spacing:0;
 font-size:var(--fs-micro);white-space:nowrap}
table.corr th.ccol{vertical-align:bottom;text-align:center;max-width:5.5rem;
 white-space:normal;line-height:1.2}
table.corr th[scope=row]{text-align:left;position:sticky;left:0;background:var(--bg2);
 z-index:1;padding-right:var(--s2)}
td.cc{min-width:4.2rem;text-align:center;border-radius:5px;padding:4px 5px;
 border:1px solid var(--line);font-size:var(--fs-micro);color:var(--text)}
td.cc .cg{margin-right:3px;font-weight:700}
td.cc .cr{font-weight:640}
td.cc .cn{display:block;color:var(--faint);font-size:9px;letter-spacing:.04em}
td.cc.thin{background:transparent;border-style:dashed;color:var(--faint)}
td.cc.pad,table.corr td.pad{border:0;background:none;min-width:0}

@media (max-width:34rem){
 .smgrid{grid-template-columns:1fr}
 li.dsrow{grid-template-columns:1fr}
 li.dsrow .dsmeta{grid-column:1}
 .cmpbar{gap:var(--s2)}
}
@media print{
 table.mx thead th,table.mx th.mxname,table.corr th[scope=row]{position:static}
 figure.sm{break-inside:avoid}
 li.dsrow{break-inside:avoid}
 .cmppick select{border:0;padding:0}
}
"""


# --------------------------------------------------------------------------
# Self-check + standalone preview: python -m src.dashboard_charts
# --------------------------------------------------------------------------
def _preview(d: dict) -> str:
    from .dashboard_assets import CSS
    blocks = [
        ("Small multiples", "Every test at once, each against its own normal range.",
         small_multiples(d)),
        ("Two days side by side", "What changed between one day and another.",
         compare_days(d)),
        ("Spread of every reading", "Where each reading sat relative to normal.",
         distribution_strip(d)),
        ("The whole matrix", "Tests down, days across, normal range pinned.",
         matrix_table(d)),
        ("How the tests moved together", "Descriptive only.", correlation_grid(d)),
    ]
    body = "".join(f'<section class="panel"><h2>{_esc(t)}</h2>'
                   f'<p class="lede">{_esc(s)}</p>{h}</section>'
                   for t, s, h in blocks)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Chart preview</title><style>" + CSS + CHART_CSS +
            "</style></head><body><div class=\"wrap\">"
            "<h1 style=\"margin:2rem 0 1rem\">Chart preview</h1>" + body +
            "</div></body></html>")


def _selfcheck() -> None:
    import json
    d = json.loads(C.LABS_JSON.read_text(encoding="utf-8"))
    for name, fn in (("small_multiples", small_multiples),
                     ("compare_days", compare_days),
                     ("distribution_strip", distribution_strip),
                     ("matrix_table", matrix_table),
                     ("correlation_grid", correlation_grid)):
        h = fn(d)
        assert h and "<" in h, f"{name} produced nothing"
        assert "http" not in h, f"{name} emitted a URL"
        assert "<script" not in h, f"{name} emitted a script tag"
        print(f"  {name:<20} {len(h):>7,} chars")

    # Empty input must render an empty state, never a traceback (D-rule in
    # dashboard_assets: a missing block is a message, not a 500).
    for fn in (small_multiples, compare_days, distribution_strip,
               matrix_table, correlation_grid):
        assert "empty" in fn({})

    # The range is the thing the reader asked for: it must be on every chart.
    assert "normal" in small_multiples(d) and "spark-band" in small_multiples(d)
    assert "Normal range" in compare_days(d) and "Normal range" in matrix_table(d)
    assert "ds-band" in distribution_strip(d)
    assert "not mean one caused the other" in correlation_grid(d)

    # Nothing below the suppression floor may leak a coefficient.
    import re
    for cell in re.findall(r'<td class="cc thin"[^>]*>', correlation_grid(d)):
        assert "data-r" not in cell, "suppressed pair still printed a number"

    out = C.DIST / "charts-preview.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_preview(d), encoding="utf-8")
    print(f"  preview              {out}")


if __name__ == "__main__":
    _selfcheck()
    print("dashboard_charts: ok")
