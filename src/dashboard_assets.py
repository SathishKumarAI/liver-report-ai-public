"""The dashboard's presentation layer: stylesheet, client script, HTML builders.

Owns: every byte of CSS and JS that ships in dist/dashboard.html, the inline-SVG
sparkline, and one HTML-fragment builder per tab. Nothing here reaches the
network, the filesystem, or a template engine -- the page must open by
double-click on a relative's laptop with no internet (docs/RESEARCH.md).

Does NOT own: the data. Every builder takes the parsed labs.json dict and reads
it defensively; a missing block renders an empty state, never a traceback and
never an invented number. It also does not own the build: src/build.py assembles
the file and enforces the human_verified gate (D11).

Two rules the markup exists to satisfy:
  * Status is encoded by SHAPE and LETTER as well as colour. A colour-blind
    reader, and a greyscale ward printer, must still see which value is high.
  * Tabs are plain sections, hidden only once JS announces itself. With JS off,
    and on paper, every panel is present and readable.
"""

from __future__ import annotations

import html
import json

from . import config as C

# FHIR interpretation code -> (glyph, letter, severity class). The glyph is the
# load-bearing part: it survives greyscale printing, the colour does not.
FLAGS = {"HH": ("▲▲", "crit"), "H": ("▲", "high"), "LL": ("▼▼", "crit"),
         "L": ("▼", "low"), "A": ("◆", "high"), "N": ("●", "norm")}


def _esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _num(v) -> str:
    """Trim float noise without ever changing the value's magnitude."""
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


def _shade(hexcol: str, f: float) -> str:
    """Scale a Mocha accent toward black for the light theme.

    Derived, not hardcoded, so PALETTE stays the single source of hue. Mocha
    accents are pastel: on white and on paper they fail contrast until darkened.
    """
    return "#%02x%02x%02x" % tuple(
        min(255, int(int(hexcol[i:i + 2], 16) * f)) for i in (1, 3, 5))


P = C.PALETTE
# `faint` is derived from subtext rather than taken from overlay: overlay on base
# measures ~3.3:1, which reads as "greyed out" rather than "secondary". Darkening
# subtext keeps the Mocha hue and lands near 6:1.
_DARK = {"bg": P["base"], "bg2": P["mantle"], "surface": P["surface0"],
         "line": P["surface1"], "text": P["text"], "dim": P["subtext"],
         "faint": _shade(P["subtext"], 0.88), "band": P["surface1"],
         "accent": P["blue"], "accent2": P["lavender"], "high": P["peach"],
         "low": P["blue"], "crit": P["red"], "norm": P["green"],
         "shadow": "0 1px 2px rgba(0,0,0,.30),0 6px 16px -12px rgba(0,0,0,.55)"}
# Light theme: neutrals are plain greys (Mocha supplies no light neutrals);
# every accent is the same hue, darkened for contrast on white and on paper.
_LIGHT = dict(_DARK, bg="#fbfbfd", bg2="#f2f2f7", surface="#ffffff",
              line="#dcdce5", text="#17171d", dim="#4e4e59", faint="#6b6b77",
              band="#e9e9f2",
              shadow="0 1px 2px rgba(23,23,29,.06),0 8px 20px -16px rgba(23,23,29,.28)",
              **{k: _shade(_DARK[k], 0.55)
                 for k in ("accent", "accent2", "high", "low", "crit", "norm")})
_v = lambda d: "".join(f"--{k}:{x};" for k, x in d.items())  # noqa: E731

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{""" + _v(_DARK) + """color-scheme:dark light;
 --s1:.25rem;--s2:.5rem;--s3:1rem;--s4:1.5rem;--s5:2rem;--s6:3rem;
 --fs-micro:.72rem;--fs-tiny:.8125rem;--fs-sub:.9375rem;--fs-body:1rem;
 --fs-h3:1.0625rem;--fs-h2:1.3125rem;--fs-h1:1.625rem;--fs-num:2.125rem;
 --radius:14px;--maxw:76rem}
@media (prefers-color-scheme:light){:root{""" + _v(_LIGHT) + """}}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font-size:var(--fs-body);line-height:1.55;
 font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
 font-variant-numeric:tabular-nums;text-rendering:optimizeLegibility}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 var(--s4) var(--s6)}
h1,h2,h3{line-height:1.25;margin:0;letter-spacing:-.011em}
h1{font-size:var(--fs-h1);font-weight:650;letter-spacing:-.02em}
h2{font-size:var(--fs-h2);font-weight:640;margin:0 0 var(--s1)}
h3{font-size:var(--fs-h3);font-weight:620}
p{margin:var(--s1) 0}a{color:var(--accent)}
.lede{color:var(--dim);font-size:var(--fs-sub);max-width:44rem;margin:0 0 var(--s4)}
.eyebrow{font-size:var(--fs-micro);letter-spacing:.11em;text-transform:uppercase;
 color:var(--dim);font-weight:670;margin:var(--s5) 0 var(--s2)}
.eyebrow:first-child{margin-top:0}
.sub{color:var(--dim);font-size:var(--fs-sub)}
.tiny{color:var(--faint);font-size:var(--fs-tiny)}
.empty{color:var(--dim);font-style:italic}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}

/* ---- header band: what this is, what it covers, what it is not ---- */
header.top{border-bottom:1px solid var(--line);background:var(--bg2)}
header.top .wrap{padding:var(--s4) var(--s4) 0}
.masthead{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--s2) var(--s3)}
.masthead .who{color:var(--dim);font-size:var(--fs-sub)}
dl.facts{display:flex;flex-wrap:wrap;gap:var(--s2) var(--s5);margin:var(--s3) 0 0}
dl.facts>div{min-width:0}
dl.facts dt{font-size:var(--fs-micro);letter-spacing:.09em;text-transform:uppercase;
 color:var(--faint);font-weight:640}
dl.facts dd{margin:2px 0 0;font-size:var(--fs-sub);font-weight:600;color:var(--text)}
dl.facts dd .lo{font-weight:400;color:var(--dim)}
.verify{margin:var(--s3) 0 0;color:var(--dim);font-size:var(--fs-tiny);max-width:52rem}
.verify .pill{margin-right:var(--s1);vertical-align:1px}
.notice{margin:var(--s3) 0 0;padding:var(--s2) 0 var(--s2) var(--s3);
 border-left:3px solid var(--accent2);color:var(--dim);font-size:var(--fs-sub);max-width:52rem}
.notice b{color:var(--text);font-weight:620}

nav.tabs{display:flex;gap:2px;overflow-x:auto;margin-top:var(--s3);scrollbar-width:thin}
nav.tabs button{flex:0 0 auto;background:none;border:0;border-bottom:2px solid transparent;
 color:var(--dim);font:inherit;font-size:var(--fs-sub);padding:var(--s2) var(--s3);
 cursor:pointer;white-space:nowrap;border-radius:8px 8px 0 0;
 transition:color .15s ease,background-color .15s ease}
nav.tabs button:hover{color:var(--text);background:var(--surface)}
nav.tabs button[aria-selected=true]{color:var(--text);font-weight:640;
 border-bottom-color:var(--accent)}

/* ---- cards ---- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
 padding:var(--s3);margin:var(--s2) 0 var(--s3);box-shadow:var(--shadow)}
.grid{display:grid;gap:var(--s3);align-items:start;
 grid-template-columns:repeat(auto-fill,minmax(15rem,1fr))}

/* ---- headline tiles: 1-up phone, 2-up tablet (last spans), 5-up desktop ---- */
.tiles{display:grid;gap:var(--s2);grid-template-columns:1fr;margin-bottom:var(--s3)}
.tiles>.card{margin:0}
@media (min-width:34rem){.tiles{grid-template-columns:repeat(2,1fr);gap:var(--s3)}
 .tiles>.card:last-child:nth-child(odd){grid-column:1/-1}}
@media (min-width:72rem){.tiles{grid-template-columns:repeat(5,1fr)}
 .tiles>.card:last-child:nth-child(odd){grid-column:auto}}
.tile{display:flex;flex-direction:column}
.tile .thead{display:flex;align-items:flex-start;justify-content:space-between;
 gap:var(--s2);margin-bottom:var(--s1)}
.tile .tlabel{font-size:var(--fs-sub);font-weight:620;color:var(--dim);line-height:1.3}
.tile .val{font-size:var(--fs-num);font-weight:650;letter-spacing:-.025em;line-height:1.05;
 display:flex;align-items:baseline;gap:.3rem;flex-wrap:wrap;margin:0}
.tile .unit{font-size:var(--fs-tiny);color:var(--dim);font-weight:500;letter-spacing:0}
.tile .dir{margin-top:var(--s1)}
.tile .plain{color:var(--dim);font-size:var(--fs-tiny);line-height:1.5;
 margin:var(--s2) 0 0;padding-top:var(--s2);border-top:1px solid var(--line)}
.flag{display:inline-flex;align-items:center;gap:.15rem;font-size:var(--fs-micro);
 font-weight:700;padding:.05rem .35rem;border-radius:6px;border:1px solid currentColor;
 line-height:1.5;white-space:nowrap}
.f-high{color:var(--high)}.f-low{color:var(--low)}
.f-crit{color:var(--crit)}.f-norm{color:var(--norm)}
.dir{font-size:var(--fs-tiny);color:var(--dim)}.dir b{font-weight:640;color:var(--text)}
.pill{display:inline-block;font-size:var(--fs-micro);letter-spacing:.07em;
 text-transform:uppercase;border:1px solid var(--line);border-radius:999px;
 padding:.05rem .5rem;color:var(--dim);font-weight:640;white-space:nowrap}
.sev-critical{color:var(--crit);border-color:currentColor}
.sev-high{color:var(--high);border-color:currentColor}
.sev-moderate{color:var(--accent2);border-color:currentColor}.sev-info{color:var(--dim)}

/* ---- what the team is watching: one block per finding, not per analyte ---- */
.watch{display:grid;gap:var(--s2);margin:0;padding:0;list-style:none}
.watch>li{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
 padding:var(--s3);box-shadow:var(--shadow);border-left:3px solid var(--line)}
.watch>li.w-critical{border-left-color:var(--crit)}
.watch>li.w-high{border-left-color:var(--high)}
.watch>li.w-moderate{border-left-color:var(--accent2)}
.watch>li.w-info{border-left-color:var(--line)}
.watch .whead{display:flex;flex-direction:row-reverse;gap:var(--s3);align-items:baseline;
 justify-content:space-between}
.watch .wtitle{font-size:var(--fs-body);font-weight:620;line-height:1.4;margin:0;
 flex:1 1 auto;min-width:0}
.watch .whead .pill{flex:0 0 auto}
.watch .wdetail{color:var(--dim);font-size:var(--fs-sub);margin:var(--s1) 0 0}
.watch ul.items{margin:var(--s2) 0 0;padding:0;list-style:none;display:grid;gap:var(--s1)}
.watch ul.items li{font-size:var(--fs-sub);color:var(--dim);
 padding-left:var(--s3);text-indent:calc(var(--s3) * -1)}
.watch ul.items b{color:var(--text);font-weight:620}
ul.plainlist{margin:var(--s1) 0;padding-left:1.1rem}ul.plainlist li{margin:var(--s1) 0}

/* ---- sparklines ---- */
/* The chart keeps its aspect ratio, so an unbounded width makes it absurdly
   tall in a wide card (the 5th tile spans both columns on a tablet). Capping the
   width, not the height, keeps circles round and triangles triangular -- shape
   is how status is encoded, so it must not be stretched. */
figure.sparkwrap{margin:var(--s2) 0 0;max-width:22rem}
svg.spark{width:100%;height:auto;display:block;overflow:visible}
.spark-band{fill:var(--band);opacity:.5}
.spark-lim{stroke:var(--faint);stroke-width:1;stroke-dasharray:2 3;opacity:.7;
 vector-effect:non-scaling-stroke}
.spark-line{fill:none;stroke:var(--accent);stroke-width:1.75;stroke-linejoin:round;
 stroke-linecap:round;vector-effect:non-scaling-stroke}
.spark-pt{fill:var(--faint)}
.spark-out{fill:var(--high)}
.spark-now{fill:var(--accent)}
.spark-now-ring{fill:none;stroke:var(--accent);stroke-width:1.25;opacity:.55;
 vector-effect:non-scaling-stroke}
.spark-halo{fill:var(--surface)}
figcaption.ends{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;
 gap:0 var(--s2);margin-top:var(--s1);font-size:var(--fs-micro);color:var(--faint)}
figcaption.ends .ep{font-weight:640;color:var(--dim)}
figcaption.ends .ep-now{color:var(--text)}
figcaption.ends .rng{flex:1 1 auto;text-align:center;min-width:0}
.once{margin:var(--s2) 0 0;padding-top:var(--s2);border-top:1px solid var(--line);
 font-size:var(--fs-micro);color:var(--faint)}

table{border-collapse:collapse;width:100%;font-size:var(--fs-tiny)}
th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--line);
 white-space:nowrap;vertical-align:top}
th{font-weight:640;font-size:var(--fs-micro);color:var(--dim);text-transform:uppercase;
 letter-spacing:.07em}
td.n,th.n{text-align:right}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.flow th:first-child,table.flow td:first-child{position:sticky;left:0;z-index:1;
 background:var(--surface);border-right:1px solid var(--line)}
table.flow thead th{position:sticky;top:0;z-index:2;background:var(--bg2)}
table.flow thead th:first-child{z-index:3}
table.flow td .d{color:var(--faint);font-size:var(--fs-micro);margin-left:.3rem}

/* Severity trajectory */
svg.traj{width:100%;height:auto;display:block;margin-top:var(--s3)}
svg.traj .gl{stroke:var(--line);stroke-width:1}
svg.traj .ax{fill:var(--faint);font-size:11px}
svg.traj .ar{fill:var(--accent);opacity:.12}
svg.traj .ln{fill:none;stroke:var(--accent);stroke-width:2;
 stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}
svg.traj .pt{fill:var(--accent)}
svg.traj .pt.last{fill:var(--bg);stroke:var(--accent);stroke-width:2.5}
svg.traj .pv{fill:var(--text);font-size:11px;font-variant-numeric:tabular-nums}

/* Day-by-day status grid */
table.grid-map{border-collapse:separate;border-spacing:2px;font-size:var(--fs-micro);
 font-variant-numeric:tabular-nums;margin-top:var(--s3)}
table.grid-map th{font-weight:600;color:var(--subtext);text-align:left;
 padding:2px 6px;white-space:nowrap}
table.grid-map thead th{color:var(--faint);font-weight:500;text-align:center}
table.grid-map th[scope=row]{position:sticky;left:0;background:var(--bg2);z-index:1}
td.gc{min-width:3.4rem;text-align:center;padding:4px 5px;border-radius:5px;
 background:var(--surface);color:var(--text);border:1px solid transparent}
td.gc .gm{font-size:9px;font-weight:700;margin-left:2px;vertical-align:super}
td.gc.ok{opacity:.72}
td.gc.hi{background:color-mix(in srgb,var(--high) 20%,var(--surface));
 border-color:color-mix(in srgb,var(--high) 45%,transparent)}
td.gc.lo{background:color-mix(in srgb,var(--low) 20%,var(--surface));
 border-color:color-mix(in srgb,var(--low) 45%,transparent)}
td.gc.crit{background:color-mix(in srgb,var(--crit) 26%,var(--surface));
 border-color:var(--crit);font-weight:700}
td.gc.none{color:var(--faint);background:transparent;border-style:dashed;
 border-color:var(--line)}

/* Multivariate views */
svg.mv{width:100%;height:auto;display:block;margin-top:var(--s3)}
svg.mv .gl{stroke:var(--line);stroke-width:1}
svg.mv .gl.base{stroke:var(--subtext);stroke-dasharray:3 3}
svg.mv .ax{fill:var(--faint);font-size:11px}
svg.mv .mvln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;
 vector-effect:non-scaling-stroke;opacity:.9}
svg.mv .mvlab{font-size:10.5px;dominant-baseline:middle}
.mvkey{display:flex;flex-wrap:wrap;gap:var(--s3);margin-top:var(--s2);
 font-size:var(--fs-micro);color:var(--subtext)}
.mvkey .k{display:inline-flex;align-items:center;gap:5px}
.mvkey i{width:10px;height:10px;border-radius:2px;display:inline-block}
.mvgrid{grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))}
.card.mvsc h4{margin:0 0 var(--s1);font-size:var(--fs-small)}
.card.mvsc svg{width:100%;height:auto;display:block}
.card.mvsc .mvpath{fill:none;stroke:var(--accent);stroke-width:1.6;opacity:.55;
 stroke-linejoin:round;vector-effect:non-scaling-stroke}
.card.mvsc .pt{fill:var(--accent)}
.card.mvsc .pt.last{fill:var(--bg);stroke:var(--accent);stroke-width:2.5}
.card.mvsc .pv{fill:var(--subtext);font-size:10px;font-variant-numeric:tabular-nums}
.card.mvsc .ax{fill:var(--faint);font-size:10px}
.callout{border-left:3px solid var(--accent);background:var(--surface);
 padding:var(--s3) var(--s4);border-radius:0 8px 8px 0;margin:var(--s4) 0;
 color:var(--subtext);font-size:var(--fs-small)}

/* Summary scorecard: system bars and biggest movers */
.card.scorecard{margin-bottom:var(--s4)}
.sysbars{display:grid;gap:6px;margin-top:var(--s2)}
.sysrow{display:grid;grid-template-columns:7.5rem 1fr auto auto;gap:var(--s3);
 align-items:center;font-size:var(--fs-micro)}
.sysname{color:var(--subtext)}
.sysbar{background:var(--surface);border-radius:4px;height:10px;overflow:hidden}
.sysbar i{display:block;height:100%;border-radius:4px}
.sysval{font-variant-numeric:tabular-nums;color:var(--text);min-width:3rem;text-align:right}
.dir{color:var(--faint);font-size:var(--fs-micro)}
.movers{display:grid;gap:5px;margin-top:var(--s2)}
.movrow{display:grid;grid-template-columns:9rem 1fr 7.5rem 3.6rem;gap:var(--s3);
 align-items:center;font-size:var(--fs-micro)}
.movname{color:var(--subtext);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.movtrack{position:relative;height:10px;background:var(--surface);border-radius:4px}
.movtrack::before{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;
 background:var(--line)}
.movtrack i{position:absolute;top:0;height:100%;border-radius:3px}
.movval,.movpct{font-variant-numeric:tabular-nums;text-align:right}
.movval{color:var(--faint)}
.movpct.w{color:var(--high)}
.movpct.b{color:var(--ok,var(--accent))}
@media (max-width:40rem){
 .sysrow{grid-template-columns:6rem 1fr auto}
 .sysrow .dir{display:none}
 .movrow{grid-template-columns:7rem 1fr 3.4rem}
 .movrow .movval{display:none}
}

/* Patterns: severity bar, timeline, cards */
svg.sevbar{width:100%;height:20px;display:block;margin-top:var(--s3)}
.sevkey{margin-bottom:var(--s4)}
svg.tl{width:100%;height:auto;display:block;min-width:640px;margin-top:var(--s3)}
svg.tl .ax{fill:var(--faint);font-size:11px}
svg.tl .tl-lab{fill:var(--subtext);font-size:11.5px;dominant-baseline:middle}
.patgrid{grid-template-columns:repeat(auto-fit,minmax(19rem,1fr));align-items:start}
.card.pat{border-left-width:3px;border-left-style:solid}
.card.pat h3{font-size:var(--fs-small);margin:var(--s2) 0 var(--s1);line-height:1.35}
.pat-head{display:flex;align-items:center;justify-content:space-between;gap:var(--s2)}
svg.evspark{width:120px;height:26px;flex:none;opacity:.85}
.sev-edge-critical{border-left-color:var(--crit)}
.sev-edge-high{border-left-color:var(--high)}
.sev-edge-moderate{border-left-color:var(--warn,var(--high))}
.sev-edge-info{border-left-color:var(--line)}
details.sevsec{margin-top:var(--s5);border-top:1px solid var(--line);padding-top:var(--s3)}
details.sevsec>summary{cursor:pointer;color:var(--subtext);padding:var(--s2) 0;
 font-size:var(--fs-small);min-height:24px}
details.sevsec>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

/* Glossary entries carrying this patient's own course */
.card.gloss{display:grid;gap:var(--s3)}
.gloss-item p{margin:.2rem 0 0}
.gloss-course{color:var(--subtext);font-size:var(--fs-small);
 border-left:2px solid var(--line);padding-left:var(--s2)}
.reg-clinical,.reg-plain{display:none}
.reg-mode-plain .reg-plain,.reg-mode-clinical .reg-clinical{display:block}
.toggle{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.toggle button{background:none;border:0;color:var(--dim);font:inherit;font-size:var(--fs-sub);
 padding:.35rem .8rem;cursor:pointer}
.toggle button[aria-pressed=true]{background:var(--surface);color:var(--text);font-weight:640}
code,.mono{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:.9em}
.formula{background:var(--bg2);border-left:3px solid var(--accent2);padding:var(--s2) var(--s3);
 border-radius:0 8px 8px 0;overflow-x:auto}
details{border-top:1px solid var(--line);padding:var(--s2) 0}
details>summary{cursor:pointer;font-size:var(--fs-sub);border-radius:6px}
img.crop{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff}
.chat{display:flex;flex-direction:column;gap:var(--s2)}
.log{display:flex;flex-direction:column;gap:var(--s2)}
.msg{padding:var(--s2) var(--s3);border-radius:10px;max-width:46rem}
.msg.you{background:var(--bg2);align-self:flex-end}
.msg.ai{background:var(--surface);border:1px solid var(--line)}
.msg.err{border:1px dashed var(--high);color:var(--dim)}
.ask{display:flex;gap:var(--s2);flex-wrap:wrap}
.ask input{flex:1 1 16rem;background:var(--bg2);border:1px solid var(--line);border-radius:8px;
 color:inherit;font:inherit;padding:.55rem .75rem}
button.go,.cite{background:var(--surface);border:1px solid var(--line);color:var(--text);
 font:inherit;font-size:var(--fs-sub);padding:.45rem .9rem;border-radius:8px;cursor:pointer}
.cite{padding:.1rem .5rem;font-size:var(--fs-tiny);margin:.2rem .2rem 0 0}
html.js .panel[hidden]{display:none}.panel{padding:var(--s5) 0 var(--s3)}
@media (max-width:34rem){
 :root{--fs-num:1.875rem;--fs-h1:1.375rem;--fs-h2:1.1875rem}
 .wrap{padding:0 var(--s3) var(--s5)}
 header.top .wrap{padding:var(--s3) var(--s3) 0}
 dl.facts{gap:var(--s2) var(--s4)}
 .panel{padding-top:var(--s4)}
 .watch .whead{display:block}
 .watch .whead .pill{float:right;margin:0 0 var(--s1) var(--s2)}}
@media (prefers-reduced-motion:reduce){
 *,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;
  transition-duration:.001ms!important;scroll-behavior:auto!important}}
@page{size:A4;margin:12mm}
@media print{
 :root{""" + _v(_LIGHT) + """--shadow:none}
 body{background:#fff;font-size:10pt}
 header.top nav.tabs,.ask,#panel-ask .log,.noprint{display:none!important}
 html.js .panel[hidden]{display:block!important}
 .panel{break-before:page}.panel:first-of-type{break-before:auto}
 .card,.watch>li{break-inside:avoid;border-color:#bbb;box-shadow:none}
 header.top{background:#fff}
 table.flow th:first-child,table.flow td:first-child,table.flow thead th{position:static}
 table{font-size:8pt}a{text-decoration:none}
 /* The flowsheet is ~2450px wide inside an overflow-x:auto box. Browsers do
    not paginate horizontally, so on paper that box silently clipped 17 of 22
    collection-time columns -- a ward-round printout showing the first 29 hours
    of an eight-day stay, with no indication anything was missing. Release the
    scroll container and let the table reflow to the sheet. */
 .scroll{overflow:visible!important;max-width:none!important}
 table.flow{width:100%!important;table-layout:fixed;font-size:6pt;word-break:break-word}
 table.flow th,table.flow td{padding:1px 2px!important}
 table.flow .d{display:none}          /* deltas cost a column's width on paper */
 thead{display:table-header-group}    /* repeat the dates on every sheet */
 tr{break-inside:avoid}
 /* Every printed sheet must be attributable; pages 2+ carried nothing. */
 @page{margin:12mm 10mm 14mm;size:A4}}
"""

JS = """
(function(){
 document.documentElement.classList.add('js');
 var nav=document.querySelector('nav.tabs');
 var panels=[].slice.call(document.querySelectorAll('.panel'));
 if(!panels.length||!nav)return;
 var buttons=[].slice.call(nav.querySelectorAll('button[data-tab]'));
 function show(id,keepScroll){
  if(!panels.some(function(p){return p.id==='panel-'+id;}))id=panels[0].id.slice(6);
  panels.forEach(function(p){p.hidden=(p.id!=='panel-'+id);});
  buttons.forEach(function(b){
   var on=b.dataset.tab===id;
   b.setAttribute('aria-selected',on?'true':'false');
   // Roving tabindex: one stop for the whole tab bar, arrows move within it.
   b.tabIndex=on?0:-1;});
  if(location.hash!=='#'+id)history.replaceState(null,'','#'+id);
  if(!keepScroll)window.scrollTo(0,0);
 }
 nav.addEventListener('keydown',function(e){
  var i=buttons.indexOf(document.activeElement),j=null;
  if(i<0)return;
  if(e.key==='ArrowRight'||e.key==='ArrowDown')j=(i+1)%buttons.length;
  else if(e.key==='ArrowLeft'||e.key==='ArrowUp')j=(i-1+buttons.length)%buttons.length;
  else if(e.key==='Home')j=0;
  else if(e.key==='End')j=buttons.length-1;
  if(j===null)return;
  e.preventDefault();show(buttons[j].dataset.tab,true);buttons[j].focus();
 });
 // One delegated handler covers the tab bar and every in-page citation link.
 document.addEventListener('click',function(e){
  var t=e.target.closest('[data-tab],[data-goto]');
  if(t){e.preventDefault();show(t.dataset.tab||t.dataset.goto);}
  var r=e.target.closest('button[data-reg]'),fx=document.getElementById('panel-formulas');
  if(r&&fx){fx.className=fx.className.replace(/reg-mode-\\w+/,'reg-mode-'+r.dataset.reg);
   [].forEach.call(fx.querySelectorAll('button[data-reg]'),function(o){
    o.setAttribute('aria-pressed',o===r?'true':'false');});}
 });
 show((location.hash||'').slice(1)||panels[0].id.slice(6));
 window.addEventListener('hashchange',function(){show(location.hash.slice(1));});

 // Ask AI. Same-origin only; there is no remote fallback and there must not be
 // one -- this is PHI. Opened from file:// it says so plainly and stops.
 var form=document.getElementById('ask-form');
 if(!form)return;
 var log=document.getElementById('ask-log'),box=document.getElementById('ask-q');
 function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
 function add(cls,txt){var d=document.createElement('div');d.className='msg '+cls;
  d.textContent=txt;log.appendChild(d);d.scrollIntoView({block:'nearest'});return d;}
 form.addEventListener('submit',function(e){
  e.preventDefault();
  var q=box.value.trim();if(!q)return;box.value='';add('you',q);
  if(location.protocol==='file:'){
   add('err','This page is open as a file, so there is no assistant to ask. Everything '+
    'else here works offline. To use Ask AI, start the local server and open the '+
    'dashboard through it.');return;}
  var pend=add('ai','Thinking\\u2026');
  fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({question:q})})
  .then(function(r){if(!r.ok)throw new Error('server said '+r.status);return r.json();})
  .then(function(j){
   pend.innerHTML=esc(j.answer||'(no answer)').replace(/\\n/g,'<br>');
   (j.citations||[]).forEach(function(c){
    var b=document.createElement('button');b.className='cite';
    b.dataset.goto=c.tab||'summary';b.textContent=c.label||c.tab||'source';
    pend.appendChild(b);});})
  .catch(function(err){pend.className='msg err';
   pend.textContent='Could not reach the local assistant ('+err.message+
    '). The rest of the dashboard is unaffected.';});
 });
})();
"""


# --------------------------------------------------------------------------
# Fragments.
# --------------------------------------------------------------------------
def flag_badge(interp) -> str:
    """Shape + letter + colour. Any one of the three is enough to read it."""
    if not interp:
        return ""
    glyph, cls = FLAGS.get(interp, ("◆", "high"))
    return (f'<span class="flag f-{cls}" title="{_esc(interp)}">'
            f'<span aria-hidden="true">{glyph}</span>{_esc(interp)}</span>')


def direction(key: str, delta) -> str:
    """Arrow plus the word: an arrow alone does not say better or worse."""
    if delta is None:
        return '<span class="dir">no earlier value</span>'
    if abs(delta) < 1e-9:
        return '<span class="dir">→ unchanged</span>'
    up = delta > 0
    known = key in C.WORSE_WHEN_RISING or key in C.WORSE_WHEN_FALLING
    worse = (key in C.WORSE_WHEN_RISING and up) or (key in C.WORSE_WHEN_FALLING and not up)
    word = "worse" if worse else ("better" if known else "changed")
    return (f'<span class="dir">{"↑" if up else "↓"} {"+" if up else "−"}'
            f'{_num(abs(delta))} <b>{word}</b></span>')


_isnum = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731


def band_text(lo, hi) -> str:
    """The reference range in words, for the caption under a sparkline."""
    if _isnum(lo) and _isnum(hi):
        return f"normal {_num(lo)}–{_num(hi)}"
    if _isnum(hi):
        return f"normal under {_num(hi)}"
    if _isnum(lo):
        return f"normal over {_num(lo)}"
    return "no printed range"


def sparkline(vals, lo=None, hi=None, w=240, h=64) -> str:
    """One analyte over time. The y-axis is scaled to the DATA, not the range.

    Scaling to include the reference range was the earlier behaviour and it made
    every tile useless: bilirubin moving 20.2 -> 17.4 against a 0.3-1.2 range
    compressed the whole series into one flat pixel row while the band filled the
    tile. The band is now a clipped tint -- it says where normal is when normal is
    in view, and gets out of the way when it is not. The caption carries the range
    in words either way, so nothing is lost by clipping it.

    Hand-written because a charting library means a CDN request, and a CDN
    request is a PHI policy violation (docs/RESEARCH.md).
    """
    num = _isnum
    pts = [(i, v) for i, v in enumerate(vals) if num(v)]
    if not pts:
        return (f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" '
                'aria-label="no data to chart"></svg>')
    ys = [v for _, v in pts]
    dmin, dmax = min(ys), max(ys)
    if dmax == dmin:                       # a flat series still needs a mid-line
        pad = max(abs(dmin) * 0.08, 0.5)
    else:
        pad = (dmax - dmin) * 0.12
    dmin, dmax = dmin - pad, dmax + pad
    top, bot, left, right = 6.0, h - 6.0, 4.0, w - 4.0
    n = max(len(vals) - 1, 1)
    px = lambda i: round(left + i * (right - left) / n, 1)                # noqa: E731
    py = lambda v: round(bot - (v - dmin) / (dmax - dmin) * (bot - top), 1)  # noqa: E731
    clamp = lambda y: round(min(max(y, top), bot), 1)                     # noqa: E731
    out = []
    if num(lo) or num(hi):
        bt = clamp(py(hi)) if num(hi) else top
        bb = clamp(py(lo)) if num(lo) else bot
        if bb - bt > 0.5:                  # skip entirely when the band is off-chart
            out.append(f'<rect class="spark-band" x="{left}" y="{bt}" '
                       f'width="{right - left}" height="{round(bb - bt, 1)}"/>')
        for lim in (hi, lo):               # hairline only where the limit is visible
            if num(lim) and top < py(lim) < bot:
                out.append(f'<line class="spark-lim" x1="{left}" x2="{right}" '
                           f'y1="{py(lim)}" y2="{py(lim)}"/>')
    out.append('<polyline class="spark-line" points="'
               + " ".join(f"{px(i)},{py(v)}" for i, v in pts) + '"/>')
    last_i = pts[-1][0]
    for i, v in pts:
        x, y, now = px(i), py(v), i == last_i
        if now:                            # halo keeps the latest mark legible
            out.append(f'<circle class="spark-halo" cx="{x}" cy="{y}" r="5"/>')
            out.append(f'<circle class="spark-now-ring" cx="{x}" cy="{y}" r="4.6"/>')
        if num(hi) and v > hi:             # triangle up = above the reference range
            s = 4.2 if now else 3.2
            out.append(f'<path class="spark-out" d="M{x} {y - s * 1.06}'
                       f'l{s} {s * 1.75}h{-2 * s}z"/>')
        elif num(lo) and v < lo:           # triangle down = below it
            s = 4.2 if now else 3.2
            out.append(f'<path class="spark-out" d="M{x} {y + s * 1.06}'
                       f'l{s} {-s * 1.75}h{-2 * s}z"/>')
        elif now:
            out.append(f'<circle class="spark-now" cx="{x}" cy="{y}" r="2.4"/>')
        elif len(pts) <= 14:
            out.append(f'<circle class="spark-pt" cx="{x}" cy="{y}" r="1.6"/>')
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" aria-label="trend of '
            f'{len(pts)} values, {_num(ys[0])} to {_num(ys[-1])}">'
            + "".join(out) + "</svg>")


def spark_block(vals, lo=None, hi=None) -> str:
    """Sparkline plus its first / reference / latest caption.

    The end labels are HTML, not SVG text: SVG text scales with the viewBox, so
    inside a 200px tile it would render at ~7px. HTML keeps one type scale.
    """
    ys = [v for v in vals if _isnum(v)]
    if not ys:
        return sparkline(vals, lo, hi)
    if len(ys) < 2:
        # One reading is not a trend. Drawing it as a chart produced a lone dot in
        # an empty box with the same number printed at both ends; saying so in a
        # line of text is both smaller and truer.
        return (f'<p class="once">One measurement · {_esc(band_text(lo, hi))}</p>')
    return ('<figure class="sparkwrap">' + sparkline(vals, lo, hi)
            + '<figcaption class="ends">'
            f'<span class="ep">{_num(ys[0])}</span>'
            f'<span class="rng">{_esc(band_text(lo, hi))}</span>'
            f'<span class="ep ep-now">{_num(ys[-1])}</span></figcaption></figure>')


# --------------------------------------------------------------------------
# Read-only projections of labs.json. No clinical judgement is made here.
# --------------------------------------------------------------------------
def _series(d: dict) -> dict:
    """analyte -> its observations in collection order."""
    s: dict = {}
    for o in d.get("observations", []):
        s.setdefault(o.get("analyte"), []).append(o)
    for v in s.values():
        v.sort(key=lambda o: o.get("collected") or "")
    return s


def _ref(obs) -> tuple:
    for o in reversed(obs):
        r = o.get("reference") or {}
        if r.get("low") is not None or r.get("high") is not None:
            return r.get("low"), r.get("high")
    return None, None


def _delta(obs, i):
    """Change from the previous numeric value in the same series, or None."""
    v = obs[i].get("value")
    if not isinstance(v, (int, float)):
        return None
    for j in range(i - 1, -1, -1):
        p = obs[j].get("value")
        if isinstance(p, (int, float)):
            return v - p
    return None


def _label(k) -> str:
    return C.ANALYTES.get(k, {}).get("display", k or "?")


def _unit(k) -> str:
    return C.ANALYTES.get(k, {}).get("unit", "")


def _empty(msg) -> str:
    return f'<p class="empty">{_esc(msg)}</p>'


def _group_keys(ser: dict, gkey: str) -> list:
    return sorted((k for k in ser if C.ANALYTES.get(k, {}).get("group") == gkey), key=_label)


# --------------------------------------------------------------------------
# One builder per tab. Each takes the whole dataset, returns an HTML fragment.
# --------------------------------------------------------------------------
_SEV_RANK = {"critical": 0, "high": 1, "moderate": 2, "info": 3}


def _join(names: list) -> str:
    """'a', 'a and b', 'a, b and c'."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


# Subject-agreement for a sentence whose single-analyte subject becomes "N tests".
# Only the leading verb ever needs it, and only for the handful the rule engine
# actually writes; an unlisted verb is left exactly as the engine wrote it.
_PLURAL_VERB = {"has": "have", "is": "are", "was": "were", "does": "do",
                "carries": "carry", "shows": "show", "remains": "remain",
                "appears": "appear", "sits": "sit", "looks": "look"}


def group_findings(pats: list) -> list:
    """Collapse findings that say the same sentence about different analytes.

    The rule engine writes one finding per analyte, so five analytes carrying a
    critical flag produced the identical sentence five times -- which reads as
    five separate emergencies rather than one fact about five numbers.

    Grouping key is (severity, headline with the analyte's own display name cut
    out), so only findings that genuinely share a sentence AND a severity merge.
    Severity is part of the key deliberately: folding a moderate finding into a
    high one and labelling the block "high" would overstate nine findings to
    dramatise one. A headline that does not contain its analyte name simply
    groups with itself; nothing is invented.
    """
    groups: dict = {}
    for p in pats:
        head = p.get("headline") or ""
        sev = p.get("severity") or "info"
        lab = _label(p.get("analyte")) if p.get("analyte") else ""
        tpl, slot = head, -1
        if lab:
            slot = head.lower().find(lab.lower())
            if slot >= 0:
                tpl = head[:slot] + "\x00" + head[slot + len(lab):]
        g = groups.setdefault((sev, tpl), {"tpl": tpl, "head": head, "slot": slot,
                                           "sev": sev, "items": []})
        g["items"].append({"label": lab or _label(p.get("analyte")),
                           "detail": p.get("detail") or ""})
    out = list(groups.values())
    for g in out:
        g["items"].sort(key=lambda i: i["label"] or "")
    out.sort(key=lambda g: (_SEV_RANK.get(g["sev"], 9), -len(g["items"])))
    return out


def group_title(g: dict) -> str:
    """The group's one sentence, with the analyte slot filled sensibly.

    Two shapes, because English has two. When the analytes sit mid-sentence
    ("the laboratory marked X as ...") a short list reads naturally in place.
    When they are the subject ("X has risen ...") a list of ten breaks both the
    grammar and the point of grouping, so the subject becomes a count and the
    names go in the list below.
    """
    items, slot = g["items"], g["slot"]
    if len(items) < 2 or slot < 0:
        return g["head"]
    labels = [i["label"] for i in items if i["label"]]
    if not labels:
        return g["head"]
    before, after = g["tpl"].split("\x00", 1)
    if before.strip() == "" or len(labels) > 4:
        head, sep, rest = after.lstrip().partition(" ")
        after = " " + _PLURAL_VERB.get(head.lower(), head) + sep + rest
        return f"{before}{len(labels)} tests{after}"
    return before + _join(labels) + after


def _watch_item(g: dict) -> str:
    """One finding block: the sentence once, then the analytes it covers."""
    sev = g["sev"] or "info"
    body = (('<ul class="items">' + "".join(
        f'<li><b>{_esc(i["label"])}</b> — {_esc(i["detail"])}</li>'
        for i in g["items"]) + "</ul>")
        if len(g["items"]) > 1
        else f'<p class="wdetail">{_esc(g["items"][0]["detail"])}</p>')
    # Pill before title in source order so a phone can float it into the first
    # line rather than stealing a column from a five-line sentence.
    return (f'<li class="w-{_esc(sev)}"><div class="whead">'
            f'<span class="pill sev-{_esc(sev)}">{_esc(sev)}</span>'
            f'<p class="wtitle">{_esc(group_title(g))}</p></div>'
            + body + "</li>")


def summary_scorecard(d: dict, w: int = 760) -> str:
    """Direction of travel across every test, and each system's current state.

    The Summary tab led with five tiles then a long list of sentences. This puts
    the shape of the week first: how many tests moved which way, and which organ
    system sits furthest from normal right now. A reader gets the answer to
    "is he better or worse" before reading a word -- and the honest answer here
    is "both", which a list of findings cannot convey.
    """
    a = d.get("analytics") or {}
    tally, systems = a.get("tally") or {}, a.get("systems") or []
    if not tally and not systems:
        return ""

    better, worse = tally.get("better", 0), tally.get("worse", 0)
    flat, undirected = tally.get("flat", 0), tally.get("changed", 0)
    total = better + worse + flat + undirected or 1

    # "changed" is kept separate from "flat" on purpose. Those are tests where
    # the project has not asserted which direction is the bad one (white cell
    # count, MCV), and folding them into "little change" would claim something
    # about them that nobody here has decided.
    parts = (("improved", better, C.PALETTE["green"]),
             ("little change", flat, C.PALETTE["overlay"]),
             ("moved, no better/worse defined", undirected, C.PALETTE["surface2"]),
             ("moved the worse way", worse, C.PALETTE["peach"]))

    seg, x = [], 0.0
    for label, n, colour in parts:
        if not n:
            continue
        wseg = w * n / total
        seg.append(f'<rect x="{x:.1f}" y="0" width="{max(2.0, wseg - 2):.1f}" height="18" '
                   f'rx="4" fill="{colour}" opacity=".85">'
                   f'<title>{n} tests {label}</title></rect>')
        x += wseg

    legend = " ".join(
        f'<span class="k"><i style="background:{c}"></i><b>{n}</b> {t}</span>'
        for t, n, c in parts if n)

    # System state: distance outside normal, as a simple ranked bar.
    rows = ""
    if systems:
        top = max(max(s["fold"] for s in systems), 2.0)
        bars = []
        for s in sorted(systems, key=lambda s: -s["fold"]):
            pct = 100 * (s["fold"] - 1) / (top - 1) if top > 1 else 0
            arrow = ""
            if s.get("first_fold"):
                if s["fold"] > s["first_fold"] * 1.1:
                    arrow = '<span class="dir up">further out than day 1</span>'
                elif s["fold"] < s["first_fold"] * 0.9:
                    arrow = '<span class="dir down">closer to normal than day 1</span>'
            bars.append(
                f'<div class="sysrow"><span class="sysname">{_esc(s["system"])}</span>'
                f'<span class="sysbar"><i style="width:{max(2.0, pct):.1f}%;'
                f'background:{_sys_colour(s["system"])}"></i></span>'
                f'<span class="sysval">{s["fold"]:g}&times;</span>{arrow}</div>')
        rows = ('<p class="eyebrow">How far each system sits outside normal, latest reading</p>'
                '<div class="sysbars">' + "".join(bars) + "</div>"
                '<p class="tiny">1&times; is the edge of the normal range. Bars average the '
                'tests in that system, so they are a rough summary, not a score.</p>')

    return (
        '<article class="card scorecard"><h3>The week at a glance</h3>'
        '<p class="sub">Every test with at least two readings, counted by which way it '
        'moved between the first and the last.</p>'
        f'<svg class="sevbar" viewBox="0 0 {w} 18" preserveAspectRatio="none" role="img" '
        f'aria-label="{better} tests improved, {worse} moved the worse way, {flat} changed '
        f'little">{"".join(seg)}</svg><p class="mvkey sevkey">{legend}</p>'
        + rows + "</article>")


def summary_movers(d: dict, w: int = 760) -> str:
    """The biggest movers, as a diverging bar. Text lists hide magnitude."""
    movement = [m for m in ((d.get("analytics") or {}).get("movement") or [])
                if m["direction"] in ("better", "worse")][:10]
    if not movement:
        return ""

    cap = max(abs(m["pct"]) for m in movement) or 1
    rows = []
    for m in movement:
        pct = max(-cap, min(cap, m["pct"]))
        width = abs(pct) / cap * 46
        worse = m["direction"] == "worse"
        colour = C.PALETTE["peach"] if worse else C.PALETTE["green"]
        left = 50 - width if pct < 0 else 50
        rows.append(
            f'<div class="movrow"><span class="movname">{_esc(m["label"])}</span>'
            f'<span class="movtrack"><i style="left:{left:.1f}%;width:{width:.1f}%;'
            f'background:{colour}"></i></span>'
            f'<span class="movval">{m["first"]:g} &rarr; {m["last"]:g}</span>'
            f'<span class="movpct {"w" if worse else "b"}">'
            f'{"+" if m["pct"] > 0 else ""}{m["pct"]:g}%</span></div>')

    return ('<article class="card"><h3>What moved most</h3>'
            '<p class="sub">Percentage change from the first reading to the last. Bars to the '
            'right rose, to the left fell. Colour says whether that direction is the '
            'concerning one for that particular test &mdash; for some tests falling is worse.'
            '</p><div class="movers">' + "".join(rows) + "</div></article>")


def days_change_chart(d: dict, w: int = 760, h: int = 150) -> str:
    """Per-day counts of what improved, worsened and became newly abnormal."""
    per_day = (d.get("analytics") or {}).get("per_day") or []
    rows = [p for p in per_day if p["improved"] or p["worsened"] or p["newly_abnormal"]]
    if len(rows) < 2:
        return ""

    top = max(max(p["improved"], p["worsened"], p["newly_abnormal"]) for p in rows) or 1
    pad_l, pad_b, pad_t = 26, 24, 8
    pw, ph = w - pad_l - 10, h - pad_b - pad_t
    slot = pw / len(rows)
    bw = min(12.0, (slot - 10) / 3)

    bars, axis = [], []
    for i, p in enumerate(rows):
        x0 = pad_l + slot * i + (slot - bw * 3) / 2
        for j, (key, colour, label) in enumerate((
                ("improved", C.PALETTE["green"], "improved"),
                ("worsened", C.PALETTE["peach"], "moved the worse way"),
                ("newly_abnormal", C.PALETTE["red"], "newly outside normal"))):
            n = p[key]
            bh = ph * n / top
            if n:
                bars.append(
                    f'<rect x="{x0 + j * bw:.1f}" y="{pad_t + ph - bh:.1f}" '
                    f'width="{bw - 1.5:.1f}" height="{max(1.5, bh):.1f}" rx="2" '
                    f'fill="{colour}" opacity=".85"><title>{p["day"]}: {n} {label}</title>'
                    f'</rect>')
        axis.append(f'<text x="{pad_l + slot * i + slot / 2:.1f}" y="{h - 7}" class="ax" '
                    f'text-anchor="middle">{p["day"][8:10]}</text>')

    legend = " ".join(
        f'<span class="k"><i style="background:{c}"></i>{t}</span>'
        for t, c in (("improved", C.PALETTE["green"]),
                     ("moved the worse way", C.PALETTE["peach"]),
                     ("newly outside normal", C.PALETTE["red"])))

    return ('<article class="card"><h3>How much changed each day</h3>'
            '<p class="sub">Counts of tests, not severity &mdash; a day with many small '
            'movements can outrank a day with one important one. Use it to see which days '
            'were eventful, then read that day below.</p>'
            f'<svg class="mv" viewBox="0 0 {w} {h}" role="img" aria-label="Counts of tests '
            f'improving, worsening and becoming newly abnormal on each day">'
            f'<line x1="{pad_l}" y1="{pad_t + ph}" x2="{w - 10}" y2="{pad_t + ph}" '
            f'class="gl base"/>{"".join(bars)}{"".join(axis)}</svg>'
            f'<p class="mvkey">{legend}</p></article>')


def validation_quality(d: dict, w: int = 760) -> str:
    """How the extraction actually performed, as counts rather than assurances."""
    q = (d.get("analytics") or {}).get("quality") or {}
    agree = q.get("agreement") or {}
    if not agree:
        return ""
    total = sum(agree.values()) or 1

    seg, x = [], 0.0
    order = (("unanimous", C.PALETTE["green"], "all passes agreed"),
             ("majority", C.PALETTE["yellow"], "a majority agreed"),
             ("single", C.PALETTE["overlay"], "only one pass read it"),
             ("conflict", C.PALETTE["red"], "no majority"))
    for key, colour, label in order:
        n = agree.get(key, 0)
        if not n:
            continue
        wseg = w * n / total
        seg.append(f'<rect x="{x:.1f}" y="0" width="{max(2.0, wseg - 2):.1f}" height="18" '
                   f'rx="4" fill="{colour}" opacity=".85">'
                   f'<title>{n} values: {label}</title></rect>')
        x += wseg

    legend = " ".join(
        f'<span class="k"><i style="background:{c}"></i><b>{agree.get(k, 0)}</b> {t}</span>'
        for k, c, t in order if agree.get(k))

    gates = q.get("gates") or {}
    gate_rows = []
    for gate, states in sorted(gates.items()):
        tot = sum(states.values()) or 1
        passed = states.get("pass", 0)
        gate_rows.append(
            f'<div class="sysrow"><span class="sysname">{_esc(gate.replace("_", " "))}</span>'
            f'<span class="sysbar"><i style="width:{100 * passed / tot:.1f}%;'
            f'background:{C.PALETTE["green"]}"></i></span>'
            f'<span class="sysval">{passed}/{tot} passed</span></div>')

    return ('<article class="card"><h3>How the reading performed</h3>'
            '<p class="sub">Each value was read by three independent OCR passes with '
            'different preprocessing. Agreement is evidence; disagreement is the list of '
            'things a human had to look at.</p>'
            f'<svg class="sevbar" viewBox="0 0 {w} 18" preserveAspectRatio="none" role="img" '
            f'aria-label="OCR agreement across {total} values">{"".join(seg)}</svg>'
            f'<p class="mvkey sevkey">{legend}</p>'
            + ('<p class="eyebrow">Validation gates</p><div class="sysbars">'
               + "".join(gate_rows) + "</div>" if gate_rows else "")
            + f'<p class="tiny">{q.get("verified", 0)} of {q.get("charted", 0)} values were '
              'then read back against the printed page by a person.</p></article>')


def tab_summary(d: dict) -> str:
    ser, tiles, worse, better = _series(d), [], 0, 0
    for key in C.HEADLINE:
        obs = ser.get(key)
        if not obs:
            continue
        last, dl = obs[-1], _delta(obs, len(obs) - 1)
        if dl:
            up, rise = dl > 0, key in C.WORSE_WHEN_RISING
            fall = key in C.WORSE_WHEN_FALLING
            if (rise and up) or (fall and not up):
                worse += 1
            elif rise or fall:
                better += 1
        lo, hi = _ref(obs)
        tiles.append(
            '<article class="card tile"><div class="thead">'
            f'<h3 class="tlabel">{_esc(_label(key))}</h3>'
            f'{flag_badge(last.get("interpretation"))}</div>'
            f'<p class="val">{_num(last.get("value"))}<span class="unit">'
            f'{_esc(last.get("unit") or _unit(key))}</span></p>'
            f'{direction(key, dl)}'
            + spark_block([o.get("value") for o in obs], lo, hi)
            + f'<p class="plain">{_esc(C.ANALYTES.get(key, {}).get("plain", ""))}</p></article>')

    def moved(n, way):
        s = ("The one key number that changed" if n == 1
             else f"All {n} key numbers that changed")
        return f"{s} moved the {way} way."

    if not (worse or better):
        head = "There is not yet an earlier set of results to compare against."
    elif not better:
        head = moved(worse, "worse")
    elif not worse:
        head = moved(better, "better")
    else:
        head = (f"Of the key numbers that changed, {worse} moved the worse way and "
                f"{better} the better way.")
    groups = group_findings([p for p in d.get("patterns", [])
                             if "family" in (p.get("audience") or [])])
    watch = "".join(_watch_item(g) for g in groups)
    return (
        f'<h2>How things stand today</h2><p class="lede">{_esc(head)} Each number below '
        'carries an arrow for the way it moved since the last sample, and a shape for '
        'whether it sits outside the normal range.</p>'
        '<p class="eyebrow">The five numbers the team follows most</p>'
        f'<div class="tiles">{"".join(tiles) or _empty("No headline values available.")}</div>'
        + summary_scorecard(d) + summary_movers(d)
        + '<p class="eyebrow">What the team is watching</p>'
        + (f'<p class="lede">{len(groups)} findings, most important first. Where one '
           'finding covers several tests it is stated once and the tests are listed '
           f'under it.</p><ul class="watch">{watch}</ul>' if watch
           else _empty("Nothing flagged for the family view yet."))
        + '<p class="tiny">Every value here came from the hospital’s own printed report '
          'and was checked against the page image. '
          '<button class="cite" data-goto="validation">See how</button></p>')


def tab_days(d: dict) -> str:
    days: dict = {}
    for key, obs in _series(d).items():
        for i, o in enumerate(obs):
            dl = _delta(obs, i) if i else None
            prev = obs[i - 1].get("interpretation") if i else None
            days.setdefault(o.get("day"), {"when": [], "rows": [], "new": []})
            slot = days[o.get("day")]
            slot["when"].append(o.get("collected") or "")
            interp = o.get("interpretation")
            if i and interp and interp != "N" and prev in (None, "N"):
                slot["new"].append(_label(key))
            if dl is not None or (interp and interp != "N"):
                slot["rows"].append(
                    f'<tr><td>{_esc(_label(key))}</td><td class="n">{_num(o.get("value"))} '
                    f'{flag_badge(interp)}</td><td>{direction(key, dl)}</td></tr>')
    if not days:
        return "<h2>Day by day</h2>" + _empty("No observations.")
    cards = []
    for day in sorted(days, key=lambda x: (x is None, x)):
        s = days[day]
        cards.append(
            f'<div class="card"><h3>Day {_esc(day)} <span class="sub">'
            f'{_esc(min(s["when"]).replace("T", " "))}</span></h3>'
            + (f'<p class="sub">Newly outside the normal range: '
               f'<b>{_esc(", ".join(sorted(set(s["new"]))))}</b></p>' if s["new"] else "")
            + (f'<div class="scroll"><table><tbody>{"".join(s["rows"])}</tbody></table></div>'
               if s["rows"] else _empty("Nothing changed against the previous sample."))
            + "</div>")
    return ('<h2>Day by day</h2>' + days_change_chart(d)
            + '<p class="sub">One card per day of admission: what moved, '
            'and what crossed out of the normal range for the first time.</p>' + "".join(cards))


def _day_labels(d: dict) -> list:
    return [s[8:10] + " " + ("Aug" if s[5:7] == "08" else s[5:7]) for s in d.get("days", [])]


def score_trajectory(d: dict, w: int = 760, h: int = 190) -> str:
    """MELD-Na across the stay: the one number that summarises severity.

    Drawn as a proper chart rather than a sparkline because it is the headline
    trajectory -- a reader should be able to read a value off it. The scale is
    pinned to 6-40, MELD's actual range, so the line's height means something
    absolute rather than being stretched to fill the box.
    """
    rows = [r for r in d.get("scores", []) if (r.get("meld_na") or {}).get("value") is not None]
    if len(rows) < 2:
        return ""

    vals = [r["meld_na"]["value"] for r in rows]
    labels = [r.get("date", r.get("collected", ""))[8:10] for r in rows]
    lo, hi = 6, 40
    pad_l, pad_b, pad_t = 34, 22, 10
    plot_w, plot_h = w - pad_l - 8, h - pad_b - pad_t

    def x(i):
        return pad_l + (plot_w * i / max(1, len(vals) - 1))

    def y(v):
        return pad_t + plot_h * (1 - (v - lo) / (hi - lo))

    grid = "".join(
        f'<line x1="{pad_l}" y1="{y(g):.1f}" x2="{w - 8}" y2="{y(g):.1f}" class="gl"/>'
        f'<text x="{pad_l - 6}" y="{y(g) + 4:.1f}" class="ax" text-anchor="end">{g}</text>'
        for g in (10, 20, 30, 40))

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    area = (f'{pad_l},{y(lo):.1f} ' + pts + f' {x(len(vals) - 1):.1f},{y(lo):.1f}')

    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{4.5 if i == len(vals) - 1 else 3}" '
        f'class="{"pt last" if i == len(vals) - 1 else "pt"}"/>'
        f'<text x="{x(i):.1f}" y="{y(v) - 10:.1f}" class="pv" text-anchor="middle">{v}</text>'
        for i, v in enumerate(vals))

    axis = "".join(
        f'<text x="{x(i):.1f}" y="{h - 6}" class="ax" text-anchor="middle">{_esc(lab)}</text>'
        for i, lab in enumerate(labels))

    return (
        '<article class="card"><h3>Overall severity, day by day (MELD-Na)</h3>'
        '<p class="sub">A single 6&ndash;40 score built from bilirubin, INR, creatinine and '
        'sodium. Higher means more severe. It summarises the tests below rather than adding '
        'anything new, and it describes severity &mdash; it does not predict an outcome.</p>'
        f'<svg class="traj" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="MELD-Na from {vals[0]} to {vals[-1]} over {len(vals)} days">'
        f'{grid}<polygon points="{area}" class="ar"/>'
        f'<polyline points="{pts}" class="ln"/>{dots}{axis}</svg></article>')


# Analytes worth a day-by-day status grid: the ones that carry the clinical
# story. A grid of all 68 would be a wall of colour nobody reads.
GRID_KEYS = [
    "bilirubin_total", "albumin", "ast", "inr", "ammonia",
    "creatinine", "urea", "sodium", "potassium",
    "wbc", "neutrophils_pct", "nlr", "procalcitonin",
    "platelets", "hemoglobin", "lactate",
]


def daily_grid(d: dict) -> str:
    """One row per key test, one column per day, shaded by distance outside range.

    The point of this view is pattern, not precision: a reader sees at a glance
    which day things turned and which systems moved together. Status is encoded
    by TEXT (the value and a H/L letter) as well as tint, so it survives
    greyscale printing and colour-blind readers.
    """
    days = d.get("days") or []
    if len(days) < 2:
        return ""

    by_key: dict = {}
    for o in d.get("observations", []):
        if o.get("value") is None:
            continue
        by_key.setdefault(o["analyte"], {}).setdefault(o["collected"][:10], []).append(o)

    keys = [k for k in GRID_KEYS if k in by_key]
    if not keys:
        return ""

    head = "".join(f"<th scope='col'>{_esc(lab)}</th>" for lab in _day_labels(d))
    rows = []
    for key in keys:
        cells = []
        for day in days:
            got = by_key[key].get(day)
            if not got:
                cells.append('<td class="gc none" aria-label="not measured">&middot;</td>')
                continue
            o = sorted(got, key=lambda r: r["collected"])[-1]
            interp = o.get("interpretation") or "N"
            cls = {"HH": "gc crit", "LL": "gc crit", "H": "gc hi",
                   "L": "gc lo", "N": "gc ok"}.get(interp, "gc ok")
            mark = {"HH": "!", "LL": "!", "H": "H", "L": "L"}.get(interp, "")
            cells.append(
                f'<td class="{cls}"><span class="gv">{_num(o["value"])}</span>'
                f'<span class="gm">{mark}</span></td>')
        rows.append(f"<tr><th scope='row'>{_esc(_label(key))}</th>{''.join(cells)}</tr>")

    return (
        '<article class="card"><h3>Day by day, at a glance</h3>'
        '<p class="sub">Each square is one day&rsquo;s result. '
        '<b>H</b> above the normal range, <b>L</b> below it, '
        '<b>!</b> a critical result, <b>&middot;</b> not measured that day. '
        'Reading across shows one test over time; reading down shows what a single day '
        'looked like.</p>'
        '<div class="scroll"><table class="grid-map"><thead><tr>'
        f'<th scope="col">Test</th>{head}</tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div></article>")


def tab_trends(d: dict) -> str:
    ser = _series(d)
    out = ['<h2>Trends</h2>', score_trajectory(d), daily_grid(d),
           '<p class="lede">Each chart covers the whole stay and is scaled to '
           'that test’s own values, so the shape of the line is the trend. The tinted band '
           'is the laboratory’s normal range where it falls inside the chart; a triangle '
           'marks a value outside it, pointing the way it went. The ringed point is the '
           'latest reading.</p>']
    for gkey, gname in C.GROUPS.items():
        keys = _group_keys(ser, gkey)
        if not keys:
            continue
        out.append(f'<p class="eyebrow">{_esc(gname)}</p><div class="grid">')
        for key in keys:
            obs = ser[key]
            lo, hi = _ref(obs)
            out.append(
                '<article class="card tile"><div class="thead">'
                f'<h3 class="tlabel">{_esc(_label(key))}</h3>'
                f'{flag_badge(obs[-1].get("interpretation"))}</div>'
                f'<p class="val">{_num(obs[-1].get("value"))}'
                f'<span class="unit">{_esc(_unit(key))}</span></p>'
                + spark_block([o.get("value") for o in obs], lo, hi) + "</article>")
        out.append("</div>")
    return "".join(out) if len(out) > 1 else out[0] + _empty("No series to chart.")


SEV_RANK = {"critical": 0, "high": 1, "moderate": 2, "info": 3}
SEV_COLOUR = {"critical": "red", "high": "peach", "moderate": "yellow", "info": "blue"}


def _sev_colour(sev: str) -> str:
    return C.PALETTE.get(SEV_COLOUR.get(sev, "blue"), C.PALETTE["blue"])


def _pattern_days(p: dict) -> list:
    return sorted({e["day"] for e in p.get("evidence", []) if isinstance(e.get("day"), int)})


def patterns_overview(pats: list, w: int = 760, h: int = 58) -> str:
    """A single proportional bar of what the rules actually found.

    72 findings as a flat list tells a reader nothing about shape. This says, in
    one glance, how much of it is genuinely urgent and how much is context --
    which matters, because two thirds of these are informational and a reader
    who does not know that will read the whole tab as alarming.
    """
    counts = {}
    for p in pats:
        counts[p.get("severity", "info")] = counts.get(p.get("severity", "info"), 0) + 1
    total = sum(counts.values()) or 1

    x, segs, keys = 0.0, [], sorted(counts, key=lambda s: SEV_RANK.get(s, 9))
    for sev in keys:
        wseg = w * counts[sev] / total
        segs.append(
            f'<rect x="{x:.1f}" y="0" width="{max(1.5, wseg - 2):.1f}" height="20" rx="4" '
            f'fill="{_sev_colour(sev)}" opacity=".85"><title>{counts[sev]} {_esc(sev)}'
            f'</title></rect>')
        x += wseg

    # Counts go in an HTML legend, not as SVG text at each segment's position:
    # the two smallest segments are a few pixels wide, so positional labels
    # ("2 critical", "6 high") simply printed on top of each other.
    legend = " ".join(
        f'<span class="k"><i style="background:{_sev_colour(s)}"></i>'
        f'<b>{counts[s]}</b> {_esc(s)}</span>' for s in keys)

    return (f'<svg class="sevbar" viewBox="0 0 {w} 20" preserveAspectRatio="none" role="img" '
            f'aria-label="{total} findings by severity">{"".join(segs)}</svg>'
            f'<p class="mvkey sevkey">{legend}</p>')


def patterns_timeline(pats: list, days: list, w: int = 760) -> str:
    """When each finding was active, as a strip per finding.

    A list says WHAT was found; this says WHEN. Reading down a column shows
    which day everything converged on -- the thing a flat list hides completely.
    """
    rows = [p for p in pats if _pattern_days(p) and SEV_RANK.get(p.get("severity"), 9) <= 2]
    if not rows or not days:
        return ""
    rows.sort(key=lambda p: (SEV_RANK.get(p.get("severity"), 9), _pattern_days(p)[0]))
    rows = rows[:18]

    label_w, cell, rh = 250, (w - 250 - 12) / len(days), 22
    h = len(rows) * rh + 26

    head = "".join(
        f'<text x="{label_w + cell * i + cell / 2:.1f}" y="12" class="ax" '
        f'text-anchor="middle">{_esc(s[8:10])}</text>' for i, s in enumerate(days))

    body = []
    for r, p in enumerate(rows):
        y = 26 + r * rh
        active = set(_pattern_days(p))
        colour = _sev_colour(p.get("severity", "info"))
        # The rule engine's headlines are written as full sentences for the
        # cards below. In a 250px row label that boilerplate eats the words that
        # actually distinguish one row from another, so strip the lead-in.
        text = (p.get("headline") or "")
        for lead in ("The laboratory marked ", "The laboratory has marked "):
            if text.startswith(lead):
                text = text[len(lead):].split(",")[0]
                text = "Critical: " + text.replace(" as a critical result", "")
                break
        text = text[:42] + ("…" if len(text) > 42 else "")
        body.append(f'<text x="0" y="{y + 13}" class="tl-lab">{_esc(text)}</text>')
        empty_stroke = f'stroke="{C.PALETTE["surface1"]}" stroke-dasharray="2 3"'
        for i in range(len(days)):
            on = (i + 1) in active
            fill = colour if on else "none"
            extra = "" if on else empty_stroke
            body.append(
                f'<rect x="{label_w + cell * i + 1:.1f}" y="{y + 4}" '
                f'width="{cell - 2:.1f}" height="{rh - 9}" rx="3" '
                f'fill="{fill}" opacity="{".85" if on else "1"}" {extra}/>')
    return (
        '<article class="card"><h3>When each finding was active</h3>'
        '<p class="sub">One row per finding, one column per day. A filled block means that '
        'finding was true on that day. Reading down a column shows which day several things '
        'happened at once. Informational findings are left out here.</p>'
        f'<div class="scroll"><svg class="tl" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="Timeline of {len(rows)} findings across {len(days)} days">'
        f'{head}{"".join(body)}</svg></div></article>')


def _evidence_spark(p: dict) -> str:
    vals = [e.get("value") for e in p.get("evidence", [])
            if isinstance(e.get("value"), (int, float))]
    if len(vals) < 3:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    w, h = 120, 26
    pts = " ".join(
        f"{w * i / (len(vals) - 1):.1f},{h - 3 - (h - 6) * (v - lo) / rng:.1f}"
        for i, v in enumerate(vals))
    colour = _sev_colour(p.get("severity", "info"))
    return (f'<svg class="evspark" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.8" '
            f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>')


def tab_patterns(d: dict) -> str:
    pats = sorted(d.get("patterns", []), key=lambda p: SEV_RANK.get(p.get("severity"), 9))
    if not pats:
        return "<h2>Patterns</h2>" + _empty("The rule engine found nothing to report.")
    days = d.get("days") or []

    groups: dict = {}
    for p in pats:
        groups.setdefault(p.get("severity", "info"), []).append(p)

    sections = []
    for sev in sorted(groups, key=lambda s: SEV_RANK.get(s, 9)):
        items = groups[sev]
        cards = []
        for p in items:
            ev = "".join(
                f'<tr><td>Day {_esc(e.get("day"))}</td><td class="n">{_num(e.get("value"))}</td>'
                f'<td>{_esc(e.get("note", ""))}</td></tr>' for e in p.get("evidence", []))
            cards.append(
                f'<div class="card pat sev-edge-{_esc(sev)}">'
                f'<div class="pat-head"><span class="pill sev-{_esc(sev)}">{_esc(sev)}</span>'
                f'{_evidence_spark(p)}</div>'
                f'<h3>{_esc(p.get("headline"))}</h3><p>{_esc(p.get("detail"))}</p>'
                + (f'<details><summary>Show the numbers</summary><div class="scroll">'
                   f'<table><tbody>{ev}</tbody></table></div></details>' if ev else "")
                + (f'<p class="tiny">{_esc(_label(p.get("analyte")))} '
                   '<button class="cite" data-goto="trends">see the trend</button></p>'
                   if p.get("analyte") else "") + "</div>")

        body = f'<div class="grid patgrid">{"".join(cards)}</div>'
        # Informational findings are context, not alarm. Collapsed so the tab
        # opens on what actually matters -- 46 of 72 findings here are info.
        if sev == "info":
            sections.append(
                f'<details class="sevsec"><summary><b>{len(items)}</b> informational '
                f'findings &mdash; context rather than concern</summary>{body}</details>')
        else:
            sections.append(
                f'<p class="eyebrow">{len(items)} {_esc(sev)}</p>{body}')

    return ('<h2>Patterns the rules found</h2>'
            '<p class="lede">These come from fixed rules over the measured values &mdash; no '
            'model, no guesswork. Every finding can be traced to the numbers that triggered '
            'it. Severity describes how far the data moved, not how the patient is.</p>'
            + patterns_overview(pats) + patterns_timeline(pats, days) + "".join(sections))


def _score_table(d: dict) -> str:
    rows, names = [], []
    for s in d.get("scores", []):
        names = [k for k, v in s.items() if isinstance(v, dict)] or names
        cells = "".join(
            (f'<td class="n">{_num(s[k].get("value"))}</td>' if s[k].get("complete")
             else f'<td class="tiny">incomplete: '
                  f'{_esc(", ".join(s[k].get("missing") or ["input"]))}</td>')
            for k in names if isinstance(s.get(k), dict))
        rows.append(f'<tr><td>{_esc(str(s.get("collected", "")).replace("T", " "))}</td>{cells}</tr>')
    if not rows:
        return ""
    head = "".join(f'<th class="n">{_esc(n)}</th>' for n in names)
    return ('<div class="eyebrow">Score trajectory</div><div class="scroll"><table><thead><tr>'
            f'<th>Collected</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def tab_doctor(d: dict) -> str:
    ser = _series(d)
    times = sorted({o.get("collected") for o in d.get("observations", []) if o.get("collected")})
    if not times:
        return "<h2>Flowsheet</h2>" + _empty("No observations.")
    head = "".join('<th class="n">' + _esc(t.replace("T", "|")).replace("|", "<br>") + "</th>"
                   for t in times)
    rows = []
    for gkey, gname in C.GROUPS.items():
        keys = _group_keys(ser, gkey)
        if not keys:
            continue
        rows.append(f'<tr><th colspan="{len(times) + 1}">{_esc(gname)}</th></tr>')
        for key in keys:
            obs = ser[key]
            at = {o.get("collected"): i for i, o in enumerate(obs)}
            cells = []
            for t in times:
                if t not in at:
                    cells.append('<td class="n tiny">·</td>')
                    continue
                o = obs[at[t]]
                dl = _delta(obs, at[t])
                shown = _num(o["value"]) if o.get("value") is not None else _esc(o.get("text"))
                dtxt = (f'<span class="d">{"+" if dl > 0 else "−"}{_num(abs(dl))}</span>'
                        if dl else "")
                cells.append(f'<td class="n">{shown} {flag_badge(o.get("interpretation"))}{dtxt}</td>')
            rows.append(f'<tr><td>{_esc(_label(key))} <span class="tiny">{_esc(_unit(key))}'
                        f'</span></td>{"".join(cells)}</tr>')
    crit = "".join(f'<tr><td>{_esc(_label(o.get("analyte")))}</td><td>'
                   f'{_esc((o.get("collected") or "").replace("T", " "))}</td>'
                   f'<td class="n">{_num(o.get("value"))} {flag_badge(o.get("interpretation"))}'
                   '</td></tr>'
                   for o in d.get("observations", []) if o.get("interpretation") in ("HH", "LL"))
    return ('<h2>Flowsheet</h2><p class="sub">Analytes down, collection times across. Each cell '
            'is value, printed flag, and change from the previous sample of that analyte.</p>'
            f'<div class="scroll"><table class="flow"><thead><tr><th>Analyte</th>{head}</tr>'
            f'</thead><tbody>{"".join(rows)}</tbody></table></div>' + _score_table(d)
            + '<div class="eyebrow">Critical values</div>'
            + (f'<div class="scroll"><table><tbody>{crit}</tbody></table></div>' if crit
               else _empty("No value flagged HH or LL.")))


def tab_formulas(d: dict) -> str:
    """Formulas come from the dataset with their citation. None is written from memory."""
    items = "".join(
        f'<div class="card"><h3>{_esc(f.get("name"))}</h3><div class="formula mono">'
        f'{_esc(f.get("expression", ""))}</div>'
        f'<div class="reg-plain"><p>{_esc(f.get("plain", ""))}</p></div>'
        f'<div class="reg-clinical"><p>{_esc(f.get("clinical", ""))}</p></div>'
        + (f'<p class="tiny">Source: {_esc(f.get("source"))}</p>' if f.get("source") else "")
        + (f'<p class="tiny">Not computed for this patient — missing: '
           f'{_esc(", ".join(f.get("missing") or []))}</p>' if f.get("missing") else "")
        + "</div>" for f in d.get("formulas", []))
    return ('<h2>How each number is worked out</h2><p class="sub">Switch the whole tab between '
            'plain English and clinical wording.</p>'
            '<div class="toggle noprint" role="group" aria-label="Explanation register">'
            '<button data-reg="plain" aria-pressed="true">Explain simply</button>'
            '<button data-reg="clinical" aria-pressed="false">Clinical</button></div>'
            + (items or _empty("No formulas supplied by the scoring module.")))


def tab_validation(d: dict) -> str:
    obs = d.get("observations", [])
    rows = []
    for o in obs:
        p = o.get("provenance") or {}
        # build.py writes the embedded crop as `crop_data` (already a complete
        # data: URI) and the on-disk path as `crop`. Reading a key nobody writes
        # ("crop_b64") meant the evidence image never rendered -- the Validation
        # tab displayed a file path as text, which is the one thing that tab
        # exists not to do. Values without an embedded crop fall back to the
        # served path, which works whenever the dashboard is served rather than
        # opened as a file.
        crop = p.get("crop_data")
        path = p.get("crop")
        if crop:
            img = f'<img class="crop" loading="lazy" alt="the printed value" src="{crop}">'
        elif path:
            img = (f'<img class="crop" loading="lazy" alt="the printed value" '
                   f'src="/{_esc(path)}" onerror="this.replaceWith(\'not embedded\')">')
        else:
            img = '<span class="tiny mono">no crop</span>'
        detail = "".join(
            f'<tr><td>OCR pass {_esc(k)}</td><td class="mono">{_esc(v)}</td></tr>'
            for k, v in (p.get("ocr") or {}).items()) + "".join(
            f'<tr><td>gate {_esc(k)}</td><td class="mono">{_esc(v)}</td></tr>'
            for k, v in (p.get("gates") or {}).items())
        rows.append(
            f'<details><summary>{_esc(_label(o.get("analyte")))} <b>'
            f'{_num(o["value"]) if o.get("value") is not None else _esc(o.get("text"))}</b> '
            f'{flag_badge(o.get("interpretation"))} <span class="tiny">page '
            f'{_esc(p.get("page"))} · '
            f'{"verified" if p.get("human_verified") else "NOT verified"}</span></summary>'
            f'<div class="grid"><div>{img}</div><div><table><tbody>{detail}'
            f'<tr><td>confidence</td><td class="mono">{_num(p.get("confidence"))}</td></tr>'
            '</tbody></table></div></div></details>')
    ok = sum(1 for o in obs if (o.get("provenance") or {}).get("human_verified"))
    return ('<h2>Where every number came from</h2>' + validation_quality(d)
            + f'<p class="sub">{ok} of {len(obs)} values '
            'carry a human-verified crop of the printed page. Open a row for the crop, the '
            'independent OCR passes, and the gates it cleared.</p>'
            + ("".join(rows) or _empty("No observations to validate.")))


# Distinct hues for the five organ systems. Chosen from the palette so they stay
# distinguishable in both themes; every series is ALSO labelled directly, so the
# chart never depends on telling two colours apart.
SYSTEM_COLOURS = {
    "Liver": "peach", "Clotting": "mauve", "Kidney": "blue",
    "Infection": "red", "Oxygen": "teal",
}


def _sys_colour(system: str) -> str:
    return C.PALETTE.get(SYSTEM_COLOURS.get(system, "blue"), C.PALETTE["blue"])


def mv_tracks(mv: dict, d: dict, w: int = 820, h: int = 340) -> str:
    """Every key test on one axis: how many times outside its own normal range.

    Raw units cannot share an axis -- bilirubin's ceiling is 1.2 and urea's is
    43, so one would be invisible and the other the whole chart. Expressing each
    as a multiple of its OWN limit puts them on equal terms, and the y-axis then
    reads directly: 1x is the edge of normal, 10x is ten times past it.

    Log-spaced, because the values span 1x to ~20x.
    """
    import math

    tracks = mv.get("tracks") or []
    days = d.get("days") or []
    if not tracks or len(days) < 2:
        return ""

    top = max((p["fold"] for t in tracks for p in t["points"]), default=2)
    top = max(2.0, top)
    pad_l, pad_b, pad_t, pad_r = 40, 26, 12, 118
    pw, ph = w - pad_l - pad_r, h - pad_b - pad_t

    def x(i):
        return pad_l + pw * i / max(1, len(days) - 1)

    def y(f):
        f = max(1.0, f)
        return pad_t + ph * (1 - math.log(f) / math.log(top))

    ticks = [t for t in (1, 2, 5, 10, 20, 50) if t <= top]
    grid = "".join(
        f'<line x1="{pad_l}" y1="{y(t):.1f}" x2="{pad_l + pw}" y2="{y(t):.1f}" '
        f'class="{"gl base" if t == 1 else "gl"}"/>'
        f'<text x="{pad_l - 6}" y="{y(t) + 4:.1f}" class="ax" text-anchor="end">{t}&times;</text>'
        for t in ticks)

    lines, ends = [], []
    for t in tracks:
        colour = _sys_colour(t["system"])
        pts = " ".join(f'{x(p["i"]):.1f},{y(p["fold"]):.1f}' for p in t["points"])
        lines.append(f'<polyline points="{pts}" class="mvln" stroke="{colour}"/>')
        last = t["points"][-1]
        ends.append({"x": x(last["i"]), "y": y(last["fold"]),
                     "label": t["label"], "colour": colour})

    # Push overlapping end-labels apart. Thirteen of these series finish within a
    # few pixels of each other, so without this the right-hand side is an
    # unreadable pile of overlapping words -- which is exactly the failure that
    # makes multi-series charts useless.
    ends.sort(key=lambda e: e["y"])
    # Shrink the gap rather than let the stack outgrow the plot. Shifting an
    # oversized stack upward instead pushed the topmost label off the canvas
    # entirely -- the highest series (bilirubin, ~19x) silently lost its name.
    min_gap = min(13.0, ph / max(1, len(ends)))
    for i in range(1, len(ends)):
        if ends[i]["y"] - ends[i - 1]["y"] < min_gap:
            ends[i]["y"] = ends[i - 1]["y"] + min_gap
    overflow = ends[-1]["y"] - (pad_t + ph) if ends else 0
    if overflow > 0:
        for e in ends:
            e["y"] -= overflow
    if ends and ends[0]["y"] < pad_t:      # never let the top label leave the canvas
        shift = pad_t - ends[0]["y"]
        for e in ends:
            e["y"] += shift

    labels = []
    for e in ends:
        # A leader line keeps the label tied to its series once it has moved.
        labels.append(
            f'<line x1="{e["x"] + 2:.1f}" y1="{e["y"] - 3.5:.1f}" '
            f'x2="{e["x"] + 2:.1f}" y2="{e["y"] - 3.5:.1f}" stroke="{e["colour"]}" '
            f'stroke-width="1" opacity=".5"/>'
            f'<text x="{e["x"] + 7:.1f}" y="{e["y"]:.1f}" class="mvlab" '
            f'fill="{e["colour"]}">{_esc(e["label"])}</text>')

    axis = "".join(
        f'<text x="{x(i):.1f}" y="{h - 8}" class="ax" text-anchor="middle">{s[8:10]}</text>'
        for i, s in enumerate(days))

    return (
        '<article class="card"><h3>Everything on one scale</h3>'
        '<p class="sub">Each line is one test, plotted as <b>how many times outside its own '
        'normal range</b> it sits. The baseline is 1&times;, the edge of normal. This is the '
        'only way to compare tests whose units are nothing alike &mdash; it shows which '
        'systems are furthest out and whether they move together.</p>'
        f'<svg class="mv" viewBox="0 0 {w} {h}" role="img" aria-label="Key tests as a '
        f'multiple of their own reference limit over {len(days)} days">'
        f'{grid}{"".join(lines)}{"".join(labels)}{axis}</svg>'
        + _sys_legend(mv) + "</article>")


def _sys_legend(mv: dict) -> str:
    return ('<p class="mvkey">' + " ".join(
        f'<span class="k"><i style="background:{_sys_colour(s)}"></i>{_esc(s)}</span>'
        for s in mv.get("systems", [])) + "</p>")


def mv_burden(mv: dict, d: dict, w: int = 780, h: int = 200) -> str:
    """One bar per organ system per day: the mean distance outside normal.

    Answers the question the individual charts cannot -- "which system is the
    problem today, and has that changed?"
    """
    import math

    burden = mv.get("burden") or []
    systems = mv.get("systems") or []
    days = [b for b in burden if b["systems"]]
    if len(days) < 2 or not systems:
        return ""

    top = max((s["fold"] for b in days for s in b["systems"].values()), default=2)
    top = max(2.0, top)
    pad_l, pad_b, pad_t = 40, 26, 10
    pw, ph = w - pad_l - 12, h - pad_b - pad_t
    slot = pw / len(days)
    bw = min(13.0, (slot - 8) / max(1, len(systems)))

    bars, axis = [], []
    for di, b in enumerate(days):
        x0 = pad_l + slot * di + (slot - bw * len(systems)) / 2
        for si, system in enumerate(systems):
            cell = b["systems"].get(system)
            if not cell:
                continue
            fold = max(1.0, cell["fold"])
            bh = ph * (math.log(fold) / math.log(top))
            stale = not cell.get("fresh")
            tests = ", ".join(cell.get("tests", []))
            note = ("all carried forward from an earlier day"
                    if stale else f'{cell.get("fresh", 0)} of {cell["n"]} measured that day')
            bars.append(
                f'<rect x="{x0 + si * bw:.1f}" y="{pad_t + ph - bh:.1f}" '
                f'width="{bw - 1.5:.1f}" height="{max(1.0, bh):.1f}" rx="2" '
                f'fill="{_sys_colour(system)}" opacity="{".35" if stale else ".85"}" '
                f'{"stroke-dasharray=\'2 2\' stroke=\'currentColor\'" if stale else ""}>'
                f'<title>{_esc(system)} {b["day"]}: {cell["fold"]}x outside normal. '
                f'{_esc(note)}. Tests: {_esc(tests)}</title></rect>')
        axis.append(f'<text x="{pad_l + slot * di + slot / 2:.1f}" y="{h - 8}" '
                    f'class="ax" text-anchor="middle">{b["day"][8:10]}</text>')

    base = (f'<line x1="{pad_l}" y1="{pad_t + ph}" x2="{w - 12}" y2="{pad_t + ph}" '
            f'class="gl base"/><text x="{pad_l - 6}" y="{pad_t + ph + 4}" class="ax" '
            f'text-anchor="end">1&times;</text>')

    return (
        '<article class="card"><h3>Which system is furthest out, day by day</h3>'
        '<p class="sub">Each bar averages that system&rsquo;s tests, again as a multiple of '
        'their normal limits. Taller means further from normal. <b>Faded, dashed bars are '
        'carried forward</b> &mdash; nothing in that system was measured that day. Hover any '
        'bar to see which tests it is built from. This is a rough summary, not a score: bars '
        'are only comparable across days when they are built from the same tests.</p>'
        f'<svg class="mv" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="Mean distance outside normal per organ system per day">'
        f'{base}{"".join(bars)}{"".join(axis)}</svg>' + _sys_legend(mv) + "</article>")


def mv_couples(mv: dict, w: int = 250, h: int = 210) -> str:
    """Two tests against each other, joined in date order.

    A scatter of two numbers says whether they move together. Joining the points
    in time order says which way the patient travelled, which a plain scatter
    throws away -- and that path is the whole point here.
    """
    couples = mv.get("couples") or []
    if not couples:
        return ""

    cards = []
    for c in couples:
        pts = c["points"]
        xs = [p["x"] for p in pts]
        ys = [p["y"] for p in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        sx = (x1 - x0) or 1
        sy = (y1 - y0) or 1
        pad = 34

        def px(v):
            return pad + (w - pad - 14) * (v - x0) / sx

        def py(v):
            return 12 + (h - 12 - pad) * (1 - (v - y0) / sy)

        path = " ".join(f'{px(p["x"]):.1f},{py(p["y"]):.1f}' for p in pts)
        dots = "".join(
            f'<circle cx="{px(p["x"]):.1f}" cy="{py(p["y"]):.1f}" '
            f'r="{5 if i == len(pts) - 1 else 3.4}" '
            f'class="{"pt last" if i == len(pts) - 1 else "pt"}">'
            f'<title>{p["day"]}: {c["x_label"]} {p["x"]}, {c["y_label"]} {p["y"]}</title>'
            f'</circle>' for i, p in enumerate(pts))
        ends = (f'<text x="{px(pts[0]["x"]):.1f}" y="{py(pts[0]["y"]) - 9:.1f}" '
                f'class="pv" text-anchor="middle">{pts[0]["day"][8:10]}</text>'
                f'<text x="{px(pts[-1]["x"]):.1f}" y="{py(pts[-1]["y"]) - 11:.1f}" '
                f'class="pv" text-anchor="middle">{pts[-1]["day"][8:10]}</text>')

        cards.append(
            '<article class="card mvsc"><h4>'
            f'{_esc(c["y_label"])} against {_esc(c["x_label"])}</h4>'
            f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="'
            f'{_esc(c["y_label"])} plotted against {_esc(c["x_label"])}, {len(pts)} days">'
            f'<polyline points="{path}" class="mvpath"/>{dots}{ends}'
            f'<text x="{w / 2:.0f}" y="{h - 6}" class="ax" text-anchor="middle">'
            f'{_esc(c["x_label"])} ({_esc(c["x_unit"])})</text>'
            f'<text x="10" y="{h / 2:.0f}" class="ax" text-anchor="middle" '
            f'transform="rotate(-90 10 {h / 2:.0f})">{_esc(c["y_unit"])}</text></svg>'
            '<p class="tiny">Numbers mark the first and last day. Following the line shows '
            'the direction of travel.</p></article>')

    return ('<p class="eyebrow">Do they move together?</p>'
            '<div class="grid mvgrid">' + "".join(cards) + "</div>")


def tab_multivariate(d: dict) -> str:
    mv = d.get("multivariate") or {}
    if not mv.get("tracks"):
        return '<h2>Several tests at once</h2>' + _empty("Not enough overlapping data.")
    return (
        '<h2>Several tests at once</h2>'
        '<p class="lede">The other tabs look at one test at a time. These views compare tests '
        'with each other, which is how you see a whole system moving rather than a single '
        'number twitching.</p>'
        '<div class="callout"><b>Read these as description, not statistics.</b> This is one '
        'person over eight days, and most tests were not run every day. There are no '
        'p&#8209;values, models or predictions here, and nothing on this tab can show that one '
        'thing <i>caused</i> another &mdash; only that two numbers moved at the same time.</div>'
        + mv_tracks(mv, d) + mv_burden(mv, d) + mv_couples(mv))


def tab_glossary(d: dict) -> str:
    """What each test is, plus what this patient's actually did.

    A definition alone leaves the reader to do the comparison themselves. The
    `course` line is generated from the data by build.py and is purely
    descriptive -- direction and position against the printed range, nothing
    interpretive.
    """
    entries = d.get("glossary") or []
    if entries:
        out = ['<h2>What each test means</h2>'
               '<p class="sub">What the test is, in plain English, and what this '
               'patient&rsquo;s readings did over the week.</p>']
        for gkey, gname in C.GROUPS.items():
            rows = [e for e in entries if e.get("group") == gkey]
            if not rows:
                continue
            out.append(f'<div class="eyebrow">{_esc(gname)}</div><div class="card gloss">')
            for e in rows:
                out.append(
                    f'<div class="gloss-item"><b>{_esc(e["label"])}</b>'
                    f'<p>{_esc(e["plain"])}</p>'
                    f'<p class="gloss-course">{_esc(e["course"])}</p></div>')
            out.append("</div>")
        return "".join(out)

    present = {o.get("analyte") for o in d.get("observations", [])}
    out = ['<h2>What each test means</h2>'
           '<p class="sub">One sentence each, in plain English.</p>']
    for gkey, gname in C.GROUPS.items():
        keys = [k for k, m in C.ANALYTES.items()
                if m.get("group") == gkey and (not present or k in present)]
        if keys:
            out.append(f'<div class="eyebrow">{_esc(gname)}</div><div class="card">'
                       + "".join(f'<p><b>{_esc(_label(k))}</b> — '
                                 f'{_esc(C.ANALYTES[k]["plain"])}</p>' for k in keys)
                       + "</div>")
    return "".join(out)


def tab_ask(d: dict) -> str:
    return ('<h2>Ask about this report</h2><p class="sub">Answers come from a model running on '
            'this machine only — nothing about this patient leaves the computer. If you '
            'opened this file by double-clicking it, there is no assistant running and the '
            'page will say so.</p>'
            '<div class="card chat"><div class="log" id="ask-log" aria-live="polite"></div>'
            '<form class="ask" id="ask-form"><input id="ask-q" name="q" autocomplete="off" '
            'aria-label="Your question" placeholder="e.g. why does the bilirubin matter?">'
            '<button class="go" type="submit">Ask</button></form></div>')


TABS = [("summary", "Summary", tab_summary), ("days", "Day by day", tab_days),
        ("trends", "Trends", tab_trends),
        ("multivariate", "Together", tab_multivariate),
        ("patterns", "Patterns", tab_patterns),
        ("doctor", "Doctor", tab_doctor), ("formulas", "Formulas", tab_formulas),
        ("validation", "Validation", tab_validation), ("glossary", "Glossary", tab_glossary),
        ("ask", "Ask AI", tab_ask)]


def all_tabs(data: dict) -> str:
    """Every panel, in order. build.py's one-liner."""
    return "".join(
        f'<section class="panel{" reg-mode-plain" if tid == "formulas" else ""}" '
        f'id="panel-{tid}" role="tabpanel" tabindex="-1" aria-labelledby="tab-{tid}" '
        f'aria-label="{_esc(label)}">{fn(data)}</section>'
        for tid, label, fn in TABS)


# Written out rather than taken from strftime: strftime's month name follows the
# process locale, and this page is read by a family, not by the machine that
# happened to build it.
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _date_range(days: list) -> str:
    """'4 to 11 March 2024'. Dates come in as ISO strings, or not at all."""
    from datetime import date
    got = []
    for x in days or []:
        try:
            got.append(date.fromisoformat(str(x)[:10]))
        except ValueError:
            continue
    if not got:
        return ""
    a, b = min(got), max(got)
    fmt = lambda d: f"{d.day} {_MONTHS[d.month - 1]} {d.year}"  # noqa: E731
    if a == b:
        return fmt(a)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day} to {b.day} {_MONTHS[b.month - 1]} {b.year}"
    return f"{fmt(a)} to {fmt(b)}"


def _fact(term: str, value: str) -> str:
    return f"<div><dt>{_esc(term)}</dt><dd>{value}</dd></div>"


def header_band(title: str, data: dict, meta: dict) -> str:
    """What this is, what it covers, how confirmed it is, and what it is not.

    The 'not medical advice' line is permanent and unconditional: it is not a
    dismissible banner and it does not live behind a tab, because the reader most
    likely to need it is the one least likely to go looking.
    """
    pat = dict(data.get("patient") or {}, **(meta.get("patient") or {}))
    who = " · ".join(str(x) for x in (
        f'{pat["age"]} years old' if pat.get("age") else None, pat.get("sex"),
        pat.get("facility")) if x)
    total = meta.get("total_values")
    if total is None:
        total = sum(1 for o in data.get("observations", []) if o.get("value") is not None)
    unver = meta.get("unverified") or 0
    # Honest, and deliberately undramatic: an unchecked value is not a wrong
    # value, and this line is read by someone who cannot tell the difference.
    if meta.get("provisional") and unver:
        state = ('<p class="verify"><span class="pill sev-moderate">provisional</span> '
                 f'{total - unver} of {total} values have been re-read against the '
                 'printed page so far. Every number here still comes from that report; '
                 'the check is a second pair of eyes on the reading.</p>')
    elif total:
        state = ('<p class="verify"><span class="pill">checked</span> '
                 f'All {total} values have been re-read against the printed page.</p>')
    else:
        state = ""
    rng = _date_range(data.get("days") or [])
    facts = "".join((
        _fact("Dates covered", _esc(rng)) if rng else "",
        _fact("Samples", f'{len(data.get("samples") or [])} <span class="lo">blood '
                         'draws</span>') if data.get("samples") else "",
        _fact("Values recorded", str(total)) if total else ""))
    nav = "".join(f'<button role="tab" id="tab-{tid}" data-tab="{tid}" '
                  f'aria-controls="panel-{tid}" aria-selected="false" tabindex="-1">'
                  f'{_esc(label)}</button>' for tid, label, _ in TABS)
    return ('<header class="top"><div class="wrap">'
            f'<div class="masthead"><h1>{_esc(title)}</h1>'
            + (f'<p class="who">{_esc(who)}</p>' if who else "")
            + "</div>"
            + (f'<dl class="facts">{facts}</dl>' if facts else "") + state
            + '<p class="notice">This page is a plain-English summary of laboratory values '
              'recorded during this hospital stay. <b>It is not medical advice and it is '
              'not a diagnosis.</b> Only the treating team can say what these numbers mean '
              'for this patient.</p>'
            + f'<nav class="tabs" role="tablist" aria-label="Sections">{nav}</nav>'
            + "</div></header>")


def page_shell(title: str, tabs_html: str, data_json: str, meta: dict | None = None) -> str:
    """The whole document. No external reference of any kind may appear in it."""
    meta = meta or {}
    # build.py passes the dataset as JSON, not as a dict. The header needs three
    # counts out of it; a bad payload must cost a header, never the page.
    try:
        data = json.loads(data_json or "{}")
        if not isinstance(data, dict):
            data = {}
    except ValueError:
        data = {}
    # "</" inside the payload would end the script element early. Escaping the
    # slash is legal JSON and leaves the parsed value byte-identical.
    payload = (data_json or "{}").replace("</", "<\\/")
    return ('<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow">'
            f'<title>{_esc(title)}</title><style>{CSS}</style>'
            + header_band(title, data, meta)
            + f'<main class="wrap">{tabs_html}<p class="tiny">Built '
            f'{_esc(meta.get("generated", ""))} from '
            f'{_esc(meta.get("source", "the hospital report"))}. This page is self-contained: '
            'it makes no internet connection and needs no network at all.</p></main>'
            f'<script id="labs" type="application/json">{payload}</script>'
            '<script>window.__LABS__=JSON.parse(document.getElementById("labs").textContent);'
            f'{JS}</script>')


if __name__ == "__main__":
    # Self-check. The assertion that matters is the external-reference one: a
    # single remote URL here is a PHI policy violation, not a style slip.
    _p = {"page": 12, "ocr": {"A": "3.1", "B": "3.1"}, "gates": {"ensemble": "pass"},
          "confidence": 92.4, "human_verified": True}
    demo = {
        "observations": [
            {"analyte": "bilirubin_total", "collected": "2024-03-04T06:00", "day": 1,
             "value": 3.1, "unit": "mg/dL", "interpretation": "H",
             "reference": {"low": 0.2, "high": 1.2}, "provenance": _p},
            {"analyte": "bilirubin_total", "collected": "2024-03-05T06:00", "day": 2,
             "value": 4.8, "unit": "mg/dL", "interpretation": "HH",
             "reference": {"low": 0.2, "high": 1.2}, "provenance": dict(_p, page=20)},
            {"analyte": "platelets", "collected": "2024-03-05T06:00", "day": 2, "value": 88,
             "unit": "10^3/mm^3", "interpretation": "L", "reference": {"low": 150, "high": 410},
             "provenance": {"page": 21, "human_verified": False}}],
        "scores": [{"collected": "2024-03-05T06:00", "meld3": {"value": 31, "complete": True},
                    "child_pugh": {"value": None, "complete": False,
                                   "missing": ["ascites_grade"]}}],
        "days": ["2024-03-04", "2024-03-05"],
        "samples": [{"sample_id": "A"}, {"sample_id": "B"}],
        "patterns": [{"id": "rising-run", "severity": "high", "analyte": "bilirubin_total",
                      "headline": "Bilirubin rose on both days measured",
                      "detail": "3.1 -> 4.8 mg/dL.", "evidence": [{"day": 1, "value": 3.1}],
                      "audience": ["family", "doctor"]},
                     # Two findings, one sentence: the case the grouping exists for.
                     {"id": "critical-flag", "severity": "critical",
                      "analyte": "bilirubin_total", "audience": ["family"],
                      "headline": "The laboratory marked Total bilirubin as critical.",
                      "detail": "flagged CH on day 2."},
                     {"id": "critical-flag", "severity": "critical", "analyte": "platelets",
                      "audience": ["family"],
                      "headline": "The laboratory marked Platelet count as critical.",
                      "detail": "flagged CL on day 2."}],
        "formulas": [{"name": "MELD 3.0", "expression": "see docs/CLINICAL.md",
                      "plain": "A score of how urgently a liver is failing.",
                      "clinical": "Predicts 90-day mortality in end-stage liver disease.",
                      "source": "MDCalc"}]}
    page = page_shell("Liver report — self-check", all_tabs(demo), json.dumps(demo),
                      {"patient": {"age": 36, "sex": "male"}, "generated": "self-check",
                       "provisional": True, "unverified": 1, "total_values": 3})
    C.DIST.mkdir(parents=True, exist_ok=True)
    out = C.DIST / "_assets_check.html"
    out.write_text(page, encoding="utf-8")
    for tid, _, _ in TABS:
        assert f'id="panel-{tid}"' in page, f"missing panel {tid}"
    assert "http://" not in page and "https://" not in page, "external reference in output"
    assert "spark-band" in page and "<polyline" in page, "sparkline did not render"
    assert "NOT verified" in page, "unverified provenance must be visible"
    assert "not medical advice" in page, "the disclaimer is not optional"
    assert "4 to 5 March 2024" in page, "date range missing from the header"
    assert "provisional" in page, "unverified build must say so"

    # The grouping is the defect this file was rewritten to fix: two findings
    # with one shared sentence must print that sentence once, naming both tests.
    fam = [p for p in demo["patterns"] if "family" in p["audience"]]
    gs = group_findings(fam)
    assert len(gs) == 2, f"expected 2 blocks from 3 findings, got {len(gs)}"
    crit = [g for g in gs if len(g["items"]) == 2][0]
    line = _watch_item(crit)
    assert "Platelet count and Total bilirubin as critical" in line, line
    assert line.count("The laboratory marked") == 1, "sentence repeated inside a block"

    # A sparkline whose reference band sits far below the data must not draw the
    # band at all -- that slab was what made the Ammonia tile unreadable.
    assert "spark-band" not in sparkline([14.6, 16.1, 17.4], 0.3, 1.2), "off-chart band drawn"
    assert "spark-band" in sparkline([0.4, 0.9, 1.1], 0.3, 1.2), "in-view band dropped"
    print(f"wrote {out} ({len(page):,} bytes), {len(TABS)} panels, no external refs")
