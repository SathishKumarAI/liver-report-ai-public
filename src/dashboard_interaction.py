"""Cross-filtering, filters and tooltips: BI behaviour in one offline file.

The dashboard renders everything at once, which is right for a page someone
prints or reads top to bottom, and wrong for someone interrogating it. This adds
the interaction a BI tool would give -- pick a day and the whole page answers
for that day; pick a test and it lights up everywhere it appears -- without a
framework, a build step or a network request.

Progressive enhancement throughout. With JavaScript off, every value is still on
the page; the filters simply do nothing. Nothing here is the only route to a
number.
"""

from __future__ import annotations

from . import config as C


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def filter_bar(d: dict) -> str:
    """A sticky control strip: days, systems, abnormal-only, search."""
    days = d.get("days") or []
    if not days:
        return ""

    day_chips = "".join(
        f'<button type="button" class="chip day-chip" data-day="{i + 1}" '
        f'aria-pressed="false" title="Show only {_esc(s)}">{_esc(s[8:10])}</button>'
        for i, s in enumerate(days))

    sys_chips = "".join(
        f'<button type="button" class="chip sys-chip" data-group="{_esc(k)}" '
        f'aria-pressed="false">{_esc(name)}</button>'
        for k, name in C.GROUPS.items())

    return f"""
<div class="filterbar noprint" role="region" aria-label="Filters">
  <details class="howto">
    <summary>How to use this page</summary>
    <p>Click a <b>day</b> to see only that day. Click a <b>test name</b> anywhere
    to follow it across every view. Shift-click to add more than one. Anything not
    matching is dimmed rather than hidden, so you keep your place. Press
    <kbd>Esc</kbd> or use Clear to go back to everything.</p>
  </details>

  <div class="frow">
    <span class="flabel" id="lbl-day">Day</span>
    <div class="chips" role="group" aria-labelledby="lbl-day">{day_chips}</div>
  </div>

  <div class="frow">
    <span class="flabel" id="lbl-sys">System</span>
    <div class="chips" role="group" aria-labelledby="lbl-sys">{sys_chips}</div>
  </div>

  <div class="frow">
    <label class="switch"><input type="checkbox" id="f-abnormal">
      <span>Outside normal only</span></label>
    <label class="switch"><input type="checkbox" id="f-critical">
      <span>Critical only</span></label>
    <label class="search"><span class="vh">Search tests</span>
      <input type="search" id="f-search" placeholder="Search a test…"
             autocomplete="off" spellcheck="false"></label>
    <button type="button" id="f-clear" class="clearbtn" hidden>Clear filters</button>
    <span id="f-count" class="fcount" role="status" aria-live="polite"></span>
  </div>
</div>
"""


CSS = """
/* Filter bar and cross-filtering */
.filterbar{position:sticky;top:0;z-index:40;background:var(--bg2);
 border-bottom:1px solid var(--line);padding:var(--s3) var(--s4);
 display:grid;gap:var(--s2);margin:0 calc(-1 * var(--s4)) var(--s4)}
.filterbar .frow{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap}
.flabel{font-size:var(--fs-micro);color:var(--faint);text-transform:uppercase;
 letter-spacing:.06em;min-width:3.6rem}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.chip{font:inherit;font-size:var(--fs-micro);padding:3px 10px;border-radius:999px;
 border:1px solid var(--line);background:transparent;color:var(--subtext);
 cursor:pointer;min-height:26px}
.chip:hover{border-color:var(--subtext);color:var(--text)}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);
 color:var(--bg);font-weight:600}
.chip:focus-visible,.clearbtn:focus-visible,.switch input:focus-visible,
#f-search:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.switch{display:inline-flex;align-items:center;gap:6px;font-size:var(--fs-micro);
 color:var(--subtext);cursor:pointer}
.search input{font:inherit;font-size:var(--fs-micro);padding:4px 9px;border-radius:6px;
 border:1px solid var(--line);background:var(--surface);color:var(--text);min-width:11rem}
.clearbtn{font:inherit;font-size:var(--fs-micro);padding:3px 10px;border-radius:6px;
 border:1px solid var(--high);background:transparent;color:var(--high);cursor:pointer}
.fcount{font-size:var(--fs-micro);color:var(--faint)}

/* Dimming, not hiding: a reader who loses the surrounding rows loses their place. */
.dimmed{opacity:.16;transition:opacity .12s ease}
.picked{outline:2px solid var(--accent);outline-offset:1px;border-radius:4px}
[data-analyte]{cursor:pointer}
[data-analyte]:hover{text-decoration:underline dotted;text-underline-offset:3px}

@media (prefers-reduced-motion:reduce){.dimmed{transition:none}}
@media print{.filterbar{display:none}.dimmed{opacity:1}}
@media (max-width:40rem){
 .filterbar{padding:var(--s2) var(--s3)}
 .flabel{min-width:auto;width:100%}
}

/* Delegated tooltip */
#tiptip{position:fixed;z-index:80;max-width:32ch;padding:8px 10px;border-radius:8px;
 background:var(--surface);color:var(--text);border:1px solid var(--surface2);
 box-shadow:0 8px 24px rgba(0,0,0,.45);font-size:var(--fs-micro);line-height:1.45;
 pointer-events:none;opacity:0;transform:translateY(-2px)}
#tiptip[data-open="1"]{opacity:1}
"""


JS = """
/* ---- Cross-filtering ------------------------------------------------------
   State lives in the URL hash so a view survives refresh and can be shared.
   Only analyte KEYS and day INDICES go in there -- never a measured value.  */
(function(){
  var state = {days:new Set(), analytes:new Set(), groups:new Set(),
               abnormal:false, critical:false, q:""};

  function readHash(){
    var h = location.hash.slice(1);
    if(!h) return;
    h.split("&").forEach(function(part){
      var kv = part.split("="), k = kv[0], v = decodeURIComponent(kv[1]||"");
      if(k==="d" && v) v.split(",").forEach(function(x){state.days.add(x);});
      if(k==="a" && v) v.split(",").forEach(function(x){state.analytes.add(x);});
      if(k==="g" && v) v.split(",").forEach(function(x){state.groups.add(x);});
      if(k==="ab") state.abnormal = v==="1";
      if(k==="cr") state.critical = v==="1";
      if(k==="q") state.q = v;
    });
  }

  function writeHash(){
    var tab = (document.querySelector('nav.tabs button[aria-selected="true"]')||{})
                .getAttribute ? document.querySelector('nav.tabs button[aria-selected="true"]')
                .getAttribute("data-tab") : null;
    var parts = [];
    if(tab) parts.push("tab="+tab);
    if(state.days.size) parts.push("d="+[].concat(Array.from(state.days)).join(","));
    if(state.analytes.size) parts.push("a="+Array.from(state.analytes).join(","));
    if(state.groups.size) parts.push("g="+Array.from(state.groups).join(","));
    if(state.abnormal) parts.push("ab=1");
    if(state.critical) parts.push("cr=1");
    if(state.q) parts.push("q="+encodeURIComponent(state.q));
    history.replaceState(null,"", parts.length ? "#"+parts.join("&") : location.pathname);
  }

  function active(){
    return state.days.size + state.analytes.size + state.groups.size +
           (state.abnormal?1:0) + (state.critical?1:0) + (state.q?1:0);
  }

  function matches(el){
    var day = el.getAttribute("data-day");
    var an  = el.getAttribute("data-analyte");
    var grp = el.getAttribute("data-group");
    var interp = el.getAttribute("data-interp") || "";
    if(state.days.size && day && !state.days.has(day)) return false;
    if(state.analytes.size && an && !state.analytes.has(an)) return false;
    if(state.groups.size && grp && !state.groups.has(grp)) return false;
    if(state.abnormal && interp && interp==="N") return false;
    if(state.critical && interp!=="HH" && interp!=="LL") return false;
    if(state.q && an && an.toLowerCase().indexOf(state.q.toLowerCase())<0){
      var label = (el.getAttribute("data-label")||"").toLowerCase();
      if(label.indexOf(state.q.toLowerCase())<0) return false;
    }
    return true;
  }

  function apply(){
    var n = active();
    document.querySelectorAll("[data-analyte],[data-day],[data-group]")
      .forEach(function(el){
        if(!n){ el.classList.remove("dimmed","picked"); return; }
        var ok = matches(el);
        el.classList.toggle("dimmed", !ok);
        var an = el.getAttribute("data-analyte");
        el.classList.toggle("picked", !!(ok && an && state.analytes.has(an)));
      });

    document.querySelectorAll(".day-chip").forEach(function(b){
      b.setAttribute("aria-pressed", state.days.has(b.dataset.day) ? "true":"false");
    });
    document.querySelectorAll(".sys-chip").forEach(function(b){
      b.setAttribute("aria-pressed", state.groups.has(b.dataset.group) ? "true":"false");
    });

    var clear = document.getElementById("f-clear");
    var count = document.getElementById("f-count");
    if(clear) clear.hidden = n===0;
    if(count) count.textContent = n ? (n===1 ? "1 filter active" : n+" filters active") : "";
    writeHash();
    document.dispatchEvent(new CustomEvent("dashfilter", {detail:{
      days:Array.from(state.days), analytes:Array.from(state.analytes)
    }}));
  }

  function toggle(set, value, additive){
    if(!additive) {
      var had = set.has(value); set.clear();
      if(!had) set.add(value);
    } else {
      set.has(value) ? set.delete(value) : set.add(value);
    }
  }

  document.addEventListener("click", function(e){
    var chip = e.target.closest(".day-chip");
    if(chip){ toggle(state.days, chip.dataset.day, e.shiftKey); apply(); return; }
    var sys = e.target.closest(".sys-chip");
    if(sys){ toggle(state.groups, sys.dataset.group, e.shiftKey); apply(); return; }
    if(e.target.closest("#f-clear")){
      state.days.clear(); state.analytes.clear(); state.groups.clear();
      state.abnormal = state.critical = false; state.q = "";
      var s = document.getElementById("f-search"); if(s) s.value = "";
      var a = document.getElementById("f-abnormal"); if(a) a.checked = false;
      var c = document.getElementById("f-critical"); if(c) c.checked = false;
      apply(); return;
    }
    /* Clicking a value follows that test everywhere it appears. Ignore clicks
       on real controls so we do not hijack buttons and links. */
    var host = e.target.closest("[data-analyte]");
    if(host && !e.target.closest("button,a,input,summary")){
      toggle(state.analytes, host.getAttribute("data-analyte"), e.shiftKey);
      apply();
    }
  });

  document.addEventListener("keydown", function(e){
    if(e.key==="Escape"){
      var c = document.getElementById("f-clear");
      if(c && !c.hidden){ c.click(); }
      hideTip();
    }
  });

  ["f-abnormal","f-critical"].forEach(function(id){
    document.addEventListener("change", function(e){
      if(e.target && e.target.id===id){
        state[id==="f-abnormal" ? "abnormal":"critical"] = e.target.checked;
        apply();
      }
    });
  });

  var timer=null;
  document.addEventListener("input", function(e){
    if(e.target && e.target.id==="f-search"){
      clearTimeout(timer);
      timer = setTimeout(function(){ state.q = e.target.value.trim(); apply(); }, 130);
    }
  });

  /* ---- one delegated tooltip, keyboard reachable ---- */
  var tip=null;
  function showTip(el){
    var text = el.getAttribute("data-tip") || el.getAttribute("title");
    if(!text) return;
    if(el.hasAttribute("title")){ el.setAttribute("data-tip", text); el.removeAttribute("title"); }
    if(!tip){ tip = document.createElement("div"); tip.id="tiptip"; document.body.appendChild(tip); }
    tip.textContent = text;
    tip.setAttribute("data-open","1");
    var r = el.getBoundingClientRect();
    var w = Math.min(tip.offsetWidth||260, 340);
    var left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left));
    var top = r.top > 120 ? r.top - tip.offsetHeight - 8 : r.bottom + 8;
    tip.style.left = left+"px"; tip.style.top = Math.max(8, top)+"px";
  }
  function hideTip(){ if(tip) tip.setAttribute("data-open","0"); }

  document.addEventListener("mouseover", function(e){
    var el = e.target.closest("[data-tip],[title]");
    if(el && el.closest(".panel")) showTip(el); else hideTip();
  });
  document.addEventListener("focusin", function(e){
    var el = e.target.closest("[data-tip]");
    if(el) showTip(el);
  });
  document.addEventListener("mouseout", hideTip);
  document.addEventListener("focusout", hideTip);
  window.addEventListener("scroll", hideTip, {passive:true});

  readHash();
  if(document.getElementById("f-search") && state.q)
    document.getElementById("f-search").value = state.q;
  if(state.abnormal) (document.getElementById("f-abnormal")||{}).checked = true;
  if(state.critical) (document.getElementById("f-critical")||{}).checked = true;
  apply();
})();
"""
