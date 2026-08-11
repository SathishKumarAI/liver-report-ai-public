"""The analyst view: a second dashboard built on a vendored Plotly.

Why a SEPARATE artifact rather than adding Plotly to the main dashboard:

The main dashboard is handed to a family. It must open by double-click on any
laptop, print sanely, and stay small. Adding 4.3 MB of charting library to it
would serve nobody who reads it.

This view has a different reader -- someone interrogating the data. Zoom, pan,
hover, legend toggling and linked axes genuinely help there, and are not worth
hand-writing in SVG. So Plotly earns its weight here and only here.

Both remain fully offline: the library is vendored, inlined, and the page makes
no network request. Verify with tools/check_dashboard.py.

    python tools/vendor_plotly.py     # once (cartesian bundle, no map code)
    python -m src.build_analyst
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config as C

PLOTLY = C.REPO / "vendor" / "plotly-cartesian-2.35.2.min.js"
OUT = C.DIST / "analyst.html"

# Plotly's defaults do not respect a theme and lean on colour alone. These are
# applied to every figure so the analyst view matches the rest of the project
# and stays readable without colour.
LAYOUT = {
    "paper_bgcolor": C.PALETTE["base"],
    "plot_bgcolor": C.PALETTE["mantle"],
    "font": {"color": C.PALETTE["text"], "size": 12,
             "family": "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"},
    "xaxis": {"gridcolor": C.PALETTE["surface0"], "zerolinecolor": C.PALETTE["surface1"]},
    "yaxis": {"gridcolor": C.PALETTE["surface0"], "zerolinecolor": C.PALETTE["surface1"]},
    "margin": {"l": 60, "r": 20, "t": 46, "b": 44},
    "hoverlabel": {"bgcolor": C.PALETTE["surface0"], "bordercolor": C.PALETTE["overlay"]},
    "legend": {"orientation": "h", "y": -0.22},
}

GROUP_ORDER = list(C.GROUPS)


def _series(dataset: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for o in dataset.get("observations", []):
        if o.get("value") is not None:
            out.setdefault(o["analyte"], []).append(o)
    for rows in out.values():
        rows.sort(key=lambda r: r["collected"])
    return out


def build_figures(dataset: dict) -> list[dict]:
    """One spec per figure. Reference ranges are drawn on every one of them.

    A lab value without its range is not interpretable, so every chart here
    carries the band as a shaded region and states the bounds in the title.
    """
    series = _series(dataset)
    figures: list[dict] = []

    # ---- 1. per-analyte trace with its reference band ----
    for group_key, group_name in C.GROUPS.items():
        keys = [k for k in series if C.ANALYTES.get(k, {}).get("group") == group_key]
        # Headline analytes first, then the rest alphabetically. The first trace
        # is what the chart shows on load, and alphabetical order opened the
        # liver panel on "A:G ratio" rather than bilirubin.
        keys.sort(key=lambda k: (k not in C.HEADLINE, C.ANALYTES[k]["display"]))
        if not keys:
            continue
        traces, shapes, buttons = [], [], []
        for i, key in enumerate(keys):
            rows = series[key]
            meta = C.ANALYTES[key]
            ref = rows[-1].get("reference") or {}
            lo, hi = ref.get("low"), ref.get("high")
            band = ""
            if lo is not None and hi is not None:
                band = f"normal {lo:g}–{hi:g}"
            elif hi is not None:
                band = f"normal under {hi:g}"
            elif lo is not None:
                band = f"normal above {lo:g}"

            traces.append({
                "type": "scatter", "mode": "lines+markers",
                "name": meta["display"],
                "x": [r["collected"] for r in rows],
                "y": [r["value"] for r in rows],
                "visible": i == 0,
                "line": {"width": 2.4, "color": C.PALETTE["blue"]},
                "marker": {"size": 8, "line": {"width": 1.5,
                                               "color": C.PALETTE["base"]}},
                "hovertemplate": (f"<b>{meta['display']}</b><br>%{{x|%d %b %H:%M}}"
                                  f"<br>%{{y}} {meta['unit']}<br>{band}<extra></extra>"),
            })
            buttons.append({
                "label": f"{meta['display']}",
                "method": "update",
                "args": [
                    {"visible": [j == i for j in range(len(keys))]},
                    {"title": {"text": _title(key, ref)},
                     "shapes": _band_shapes(lo, hi)},
                ],
            })

        first = series[keys[0]][-1].get("reference") or {}
        figures.append({
            "id": f"fig-{group_key}",
            "title": f"{group_name}: one test at a time, with its normal band",
            "note": "Pick a test from the menu. The shaded band is the laboratory's "
                    "normal range. Drag to zoom, double-click to reset.",
            "data": traces,
            "layout": dict(LAYOUT, **{
                "title": {"text": _title(keys[0], series[keys[0]][-1].get("reference"))},
                "shapes": _band_shapes(first.get("low"), first.get("high")),
                "updatemenus": [{
                    "buttons": buttons, "direction": "down", "showactive": True,
                    "x": 0, "xanchor": "left", "y": 1.18, "yanchor": "top",
                    "bgcolor": C.PALETTE["surface0"],
                    "bordercolor": C.PALETTE["surface2"],
                    "font": {"color": C.PALETTE["text"]},
                }],
                "showlegend": False,
            }),
        })

    # ---- 2. everything at once, as multiples of each test's own limit ----
    tracks = (dataset.get("multivariate") or {}).get("tracks") or []
    if tracks:
        data = [{
            "type": "scatter", "mode": "lines+markers",
            "name": t["label"],
            "x": [p["day"] for p in t["points"]],
            "y": [p["fold"] for p in t["points"]],
            "hovertemplate": (f"<b>{t['label']}</b><br>%{{x|%d %b}}"
                              "<br>%{y:.2f}x its own limit<extra></extra>"),
        } for t in tracks]
        figures.append({
            "id": "fig-fold",
            "title": "Every test on one axis, as a multiple of its own limit",
            "note": "1x is the edge of normal. This is the only way to compare tests "
                    "whose units are nothing alike. Click a legend entry to hide it; "
                    "double-click to isolate it.",
            "data": data,
            "layout": dict(LAYOUT, **{
                "yaxis": dict(LAYOUT["yaxis"], type="log", title={"text": "x outside normal"}),
                "shapes": [{"type": "line", "xref": "paper", "x0": 0, "x1": 1,
                            "y0": 1, "y1": 1, "line": {"color": C.PALETTE["subtext"],
                                                       "dash": "dash", "width": 1}}],
                "showlegend": True,
            }),
        })

    # ---- 3. severity trajectory ----
    scores = [r for r in dataset.get("scores", [])
              if (r.get("meld_na") or {}).get("value") is not None]
    if len(scores) > 1:
        figures.append({
            "id": "fig-meld",
            "title": "MELD-Na trajectory",
            "note": "Scale pinned to the score's real 6–40 range, so height means "
                    "something absolute. Higher is more severe. It summarises the "
                    "other tests rather than adding information.",
            "data": [{
                "type": "scatter", "mode": "lines+markers+text",
                "x": [r.get("date", r["collected"][:10]) for r in scores],
                "y": [r["meld_na"]["value"] for r in scores],
                "text": [str(r["meld_na"]["value"]) for r in scores],
                "textposition": "top center",
                "line": {"width": 3, "color": C.PALETTE["mauve"]},
                "marker": {"size": 10},
                "hovertemplate": "%{x}<br>MELD-Na %{y}<extra></extra>",
            }],
            "layout": dict(LAYOUT, **{
                "yaxis": dict(LAYOUT["yaxis"], range=[6, 41], title={"text": "MELD-Na"}),
                "showlegend": False,
            }),
        })

    # ---- 4. status heatmap: analyte x day, coloured by distance outside normal ----
    keys = [k for k in C.HEADLINE + ["urea", "wbc", "nlr", "lactate", "albumin", "ast"]
            if k in series]
    days = dataset.get("days") or []
    if keys and len(days) > 1:
        z, text = [], []
        for key in keys:
            row_z, row_t = [], []
            by_day = {}
            for r in series[key]:
                by_day[r["collected"][:10]] = r
            for day in days:
                r = by_day.get(day)
                if not r:
                    row_z.append(None)
                    row_t.append("not measured")
                    continue
                ref = r.get("reference") or {}
                lo, hi = ref.get("low"), ref.get("high")
                fold = 1.0
                if hi and r["value"] > hi:
                    fold = r["value"] / hi
                elif lo and r["value"] < lo:
                    fold = lo / r["value"]
                row_z.append(round(min(fold, 20), 2))
                row_t.append(f"{r['value']} {r.get('unit', '')} &mdash; {fold:.1f}x")
            z.append(row_z)
            text.append(row_t)
        figures.append({
            "id": "fig-heat",
            "title": "How far outside normal, by test and day",
            "note": "Darker means further from the laboratory's normal range. Blank "
                    "cells were not measured that day. Capped at 20x so one extreme "
                    "value does not flatten everything else.",
            "data": [{
                "type": "heatmap", "z": z, "text": text,
                "x": days, "y": [C.ANALYTES[k]["display"] for k in keys],
                "colorscale": [[0, C.PALETTE["surface0"]], [0.15, C.PALETTE["teal"]],
                               [0.4, C.PALETTE["yellow"]], [0.7, C.PALETTE["peach"]],
                               [1, C.PALETTE["red"]]],
                "hovertemplate": "%{y}<br>%{x}<br>%{text}<extra></extra>",
                "colorbar": {"title": {"text": "x outside"}},
            }],
            "layout": dict(LAYOUT, **{"showlegend": False,
                                      "margin": {"l": 150, "r": 20, "t": 46, "b": 44}}),
        })

    return figures


def _band_label(ref) -> str:
    lo, hi = (ref or {}).get("low"), (ref or {}).get("high")
    if lo is not None and hi is not None:
        return f"normal {lo:g}–{hi:g}"
    if hi is not None:
        return f"normal under {hi:g}"
    if lo is not None:
        return f"normal above {lo:g}"
    return "no printed reference range"


def _title(key: str, ref) -> str:
    """Chart title: name, unit only when there is one, and the normal range.

    Unitless analytes (INR, A:G ratio, the neutrophil ratio) were rendering as
    "A:G ratio ()" -- empty parentheses that look like a bug to a reader.
    """
    meta = C.ANALYTES[key]
    unit = meta.get("unit") or ""
    name = f"{meta['display']} ({unit})" if unit.strip() else meta["display"]
    return f"{name} — {_band_label(ref)}"


def _band_shapes(lo, hi) -> list[dict]:
    if lo is None and hi is None:
        return []
    y0 = lo if lo is not None else 0
    y1 = hi if hi is not None else (lo * 1.6 if lo else 1)
    return [{
        "type": "rect", "xref": "paper", "x0": 0, "x1": 1,
        "y0": y0, "y1": y1, "layer": "below",
        "fillcolor": C.PALETTE["green"], "opacity": 0.13,
        "line": {"width": 0},
    }]


def render(dataset: dict, figures: list[dict], plotly_js: str) -> str:
    P = C.PALETTE
    cards = "".join(
        f'<section class="fig"><h2>{f["title"]}</h2>'
        f'<p class="note">{f["note"]}</p><div id="{f["id"]}"></div></section>'
        for f in figures)

    specs = json.dumps([{"id": f["id"], "data": f["data"], "layout": f["layout"]}
                        for f in figures])

    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Liver report - analyst view</title>
<style>
:root{{color-scheme:dark}}
body{{margin:0;background:{P['base']};color:{P['text']};
 font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 font-variant-numeric:tabular-nums}}
header{{padding:22px 26px 14px;border-bottom:1px solid {P['surface0']}}}
h1{{margin:0;font-size:20px;letter-spacing:-.01em}}
.sub{{color:{P['subtext']};margin:6px 0 0;font-size:13.5px;max-width:80ch}}
.warn{{margin:14px 26px 0;padding:11px 14px;border-left:3px solid {P['mauve']};
 background:{P['surface0']};border-radius:0 8px 8px 0;color:{P['subtext']};
 font-size:13px;max-width:90ch}}
main{{padding:8px 26px 60px;display:grid;gap:22px}}
.fig{{background:{P['mantle']};border:1px solid {P['surface0']};border-radius:14px;
 padding:18px 18px 8px}}
.fig h2{{margin:0;font-size:15.5px}}
.note{{color:{P['subtext']};font-size:13px;margin:6px 0 10px;max-width:88ch}}
a{{color:{P['blue']}}}
@media (max-width:600px){{header,main,.warn{{padding-left:14px;padding-right:14px}}}}
</style>

<header>
  <h1>Liver report &mdash; analyst view</h1>
  <p class="sub">Interactive charts for interrogating the data: drag to zoom,
  double-click to reset, click legend entries to isolate a series. Every chart
  shows the laboratory's normal range, because a value without its range cannot
  be judged.</p>
</header>

<div class="warn"><b>This is a presentation of measured values, not a diagnosis
or a prediction.</b> One patient, eight days. Nothing here is a model or a
forecast, and nothing here can show that one thing caused another.
The plain-English view is in <a href="dashboard.html">dashboard.html</a>.</div>

<main>{cards}</main>

<script>{plotly_js}</script>
<script>
// Plotly is vendored and inlined above: this page makes no network request.
const SPECS = {specs};
const CONFIG = {{
  responsive: true,
  displaylogo: false,
  // No "send data to cloud" button. It would upload the patient's values.
  modeBarButtonsToRemove: ['sendDataToCloud', 'toImage'],
  toImageButtonOptions: {{format: 'png', scale: 2}}
}};
for (const s of SPECS) {{
  Plotly.newPlot(s.id, s.data, s.layout, CONFIG);
}}
</script>
"""


def main() -> int:
    if not PLOTLY.exists():
        raise SystemExit(
            f"Plotly is not vendored yet ({PLOTLY}).\n"
            "Run:  python tools/vendor_plotly.py\n"
            "The main dashboard does not need it."
        )
    if not C.LABS_JSON.exists():
        raise SystemExit(f"No dataset at {C.LABS_JSON}.")

    dataset = json.loads(C.LABS_JSON.read_text(encoding="utf-8"))
    figures = build_figures(dataset)
    html = render(dataset, figures, PLOTLY.read_text(encoding="utf-8", errors="ignore"))

    C.DIST.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    print(f"figures : {len(figures)}")
    print(f"written : {OUT}")
    print(f"size    : {OUT.stat().st_size / 1_048_576:.1f} MB (Plotly inlined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
