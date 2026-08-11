# Decision log — the thinking, phase by phase

Append-only. Each entry: what was decided, what forced it, and what evidence was in hand at
the time. Written so that a later session (or a different person) can tell a reasoned choice
from an accident.

> All values quoted below are from the synthetic case (`docs/SYNTHETIC-DATA.md`). The
> reasoning, the measurements of the scanner, and the page-level failures are the real ones;
> the numbers they are demonstrated on are invented.

---

## D1 — Treat the document as images, not as a PDF

**Decided:** OCR every page. Do not attempt text extraction.

**Forced by:** `pdftotext -layout` over all 112 pages returns 112 characters — one form feed
per page and nothing else. `pdfinfo` shows `Producer: IntSig Information Co., Ltd`
(CamScanner) and `pdfimages -list` shows one full-page RGB JPEG per page at ~275 dpi.

**Consequence:** there is no fallback source of truth inside the file. Every number in the
final dataset comes from OCR, which is why the validation phase is disproportionately large.

---

## D2 — The grey sample band is the load-bearing problem

**Decided:** build a dedicated extraction path for the grey metadata band, separate from
body-text OCR.

**Forced by:** a sweep for `Sample No` across the OCR output of all 112 pages returned
**zero matches**. That band is white text on a mid-grey fill; Tesseract binarises it away.
The band carries `Collection Date` — the timestamp that every observation hangs from.

Without it there is no time axis, and a dashboard about *change over days* has no days.
The failure is silent: a naive pipeline yields plausible values with no clock and nobody
notices until the chart is empty.

**Evidence the fix works** — page 40, crop the band, `-colorspace gray -resize 300% -negate
-normalize -level 20%,80% -sharpen 0x1`, then `--psm 7`:

```
Sample No <sample-id>  Collection Date 06/03/24 07:15
Ack Date 06/03/2024 09:42  Report Date 06/03/24 11:08
```

Verified against the page image by eye: exact match on all three timestamps.

**Also decided:** the *other* dark band — the `TEST | RESULT | UNIT | BIOLOGICAL REF INTERVAL`
column header — gets read for its **x positions**, not its text. It gives per-page column
boundaries, which is what makes parsing survive page skew.

---

## D3 — Parse by geometry, not by lines or keywords

**Decided:** cluster `tesseract --tsv` word boxes into lines by y-overlap, assign columns by
x, then merge wrapped fragments.

**Forced by:** page 17. The analyte is printed as `ABSOLUTE BASOPHIL` / `COUNT` on two lines,
and its unit as `10^3/mm^` / `3`. A line-oriented parser reading line 2 sees the token
`COUNT` with no value, and reading line 1 sees a value belonging to a name it has only half
of. The common open-source approach (keyword match per line) produces wrong analyte↔value
pairings here, which is the worst kind of error: well-formed, plausible, and wrong.

**Rule that falls out:** a TEST-column line with no RESULT-column word is a continuation of
the analyte above it.

---

## D4 — Sample context carries forward across pages

**Decided:** a page with no sample band inherits the sample (and therefore the timestamp) of
the last band seen.

**Forced by:** page 17 is a CBC *continuation* — it has the patient header but no sample
band, because the panel started on page 16. Roughly half the pages are continuations.
Treating a bandless page as "no data" would silently drop them.

---

## D5 — Zero pip installs

**Decided:** local binaries (`tesseract`, `pdftoppm`, `magick`) driven from Python stdlib.
No numpy, Pillow, OpenCV, pytesseract, npm or CDN.

**Forced by:** partly the PHI rule (every dependency is another thing that could phone home,
and a CDN request from the dashboard would be an outright violation), partly that all three
binaries were already installed and do the job.

Row-luminance profiling — the thing that finds the bands — is normally a numpy operation.
`magick <page> -colorspace gray -resize 1x! txt:-` returns one mean value per pixel row as
text. That is the whole feature, for free.

**Revisit if:** measured OCR disagreement on the value column exceeds ~3%, in which case
`rapidocr-onnxruntime` (~15 MB, CPU-only, offline) joins as a third voter. Not before —
paying for a dependency before the cheap approach is proven insufficient is how this
codebase would get heavy for no measured reason.

---

## D6 — Model records on FHIR R4 Observation

**Decided:** the dataset uses the FHIR `Observation` shape, extended with a custom
`provenance` block.

**Reasoning:** the decisive point is that FHIR's `interpretation` code set
(`H`, `L`, `HH`, `LL`, `N`) is exactly what the report already prints as `▲ (H)` and `(CH)`.
The lab has, in effect, published a redundant encoding of every value's position relative to
its reference range — which we turn into a validation gate at no cost (D7).

---

## D7 — The printed H/L flag is a validation gate, not decoration

**Decided:** cross-check every parsed value against the flag the lab printed next to it.

**Reasoning:** `PROTHROMBIN TIME 28.9 ▲ (H)`, reference `10.8 - 13.2`. If OCR drops the
decimal and reads `3.18`, the value now sits *below* the reference range while the page
insists it is high. Caught immediately, with no clinical knowledge required.

This catches decimal-point placement and digit-drop errors specifically — the two OCR
failure modes that do the most clinical damage, because they move a number by an order of
magnitude while leaving it looking entirely reasonable.

---

## D8 — Arithmetic invariants over clinical plausibility

**Decided:** validate primarily against algebraic identities the analyser itself guarantees
(`MCV = PCV/RBC × 10`, `total bilirubin = direct + indirect`, `INR ≈ (PT/MNPT)^ISI`,
differential percentages summing to 99–101), and only secondarily against "is this value
plausible".

**Reasoning:** plausibility checks fight the data. A patient in acute-on-chronic liver
failure is genuinely, severely abnormal — an INR of 2.41 and a procalcitonin of 2.06 are
real results, not extraction faults. A validator tuned to flag implausible values would flag
the true clinical signal and teach us to ignore it. Identities have no such conflict: they
hold regardless of how sick the patient is, so a violation is always an extraction error.

**Checked by hand before a line of the gate was written:** PT 28.9 s, mean normal PT 12.0 s,
INR 2.41. `28.9 / 12.0 = 2.408 ≈ 2.41` ✓ — three numbers from three separate cells on a
scanned page, reconciling to within 0.1%.

The report even states one of these bounds itself: *"the differential count is computed
from a total of several thousands of cells... may not add upto exactly 100. It may fall
between 99 and 101."*

---

## D9 — Do not fabricate missing clinical inputs

**Decided:** Child-Pugh and AARC render as **incomplete**, naming the specific missing
input, rather than substituting a default.

**Forced by:** both need hepatic encephalopathy grade and (Child-Pugh) ascites grade, which
are bedside findings, not lab values.

Defaulting "no encephalopathy" because the field is blank would compute a reassuringly low
score for a patient whose ammonia is 79 µmol/L against a `0 – 54` range. The dashboard
exposes these as explicit inputs and shows what is missing.

> **Superseded in part by D12** — an earlier version of this entry also claimed lactate was
> absent from the document. It is not. See below.

---

## D10 — Offline rules plus written narrative, no API

**Decided:** the interpretive layer is (a) a deterministic threshold/trend engine in code,
and (b) narrative text written from the verified dataset and embedded as static content.
No runtime model call.

**Forced by:** the PHI rule. Sending a patient's labs to any API — including Anthropic's —
is the thing we are explicitly not doing. A deterministic engine also has the property that
a clinician can audit why a flag fired, which a generated sentence does not.

---

## D11 — Export is gated in code, not by discipline

**Decided:** `build.py` refuses to emit the dashboard while any charted value has
`human_verified: false`, and prints the analyte, day, page and crop path for each.

**Reasoning:** the requirement is no wrong data points. A checklist that is *supposed* to be
completed is not a control. Making the build fail is.

**Evidence that the human gate is not ceremony.** Three OCR passes agreed and all four
automated gates passed on two values that were nonetheless wrong, and both were found only
by reading the evidence crops (`docs/OCR-NOTES.md` §8):

| Error | Why every gate passed it |
|---|---|
| Blood-gas haematocrit filed as serum PCV | Every digit was read correctly. The *label* was wrong, and no gate checks labels |
| Base excess recorded without its minus sign | The value regex never looked for a leading `-`, so there was nothing to disagree about |

**The general lesson, and the second recorded mistake in this log:** *agreement is not
inspection.* Three passes agreeing proves the glyphs were read; it cannot prove the number
was filed under the right analyte, and it cannot see a character the parser never looked for.

---

## D12 — Build the analyte dictionary from the document, not from expectations

**Decided:** every analyte name and alias in `config.ANALYTES` is taken from a frequency scan
of the actual OCR output, not from a list of tests a liver panel "should" contain.

**Forced by getting it wrong first.** An early keyword sweep searched for `LACTATE` across all
112 pages, found nothing, and concluded lactate was unavailable — which propagated into D9 and
into the research notes as a reason AARC could never be completed.

The blood-gas analyser prints it as **`Lac`**. It is present on 13 pages. Verified on page 21:
`Lac 3.2 ▲ (H)`, reference `0.500 - 2.200 mmol/L` — an elevated lactate, which is a serious
finding and was nearly dropped from the dataset by a naming assumption.

Rebuilding the dictionary from a scan of the OCR corpus surfaced the whole arterial blood gas
panel that the same assumption had hidden: `pCO2`, `pO2`, `Na+`, `K+`, `Cl-`, `Ca++`, `Hct`,
`Glu`, `tHb`, `O2Hb`, `COHb`, `MetHb`, `HHb`, `sO2`, `TCO2`, `HCO3-`, `BE`. Thirteen ABG
reports, roughly a sixth of the document.

**The scan also supplied the OCR corruption list for free** — `Het` for `Hct`, `cI-`/`Crl-`/
`Cor` for `Cl-`, `Nat` for `Na+`, `slu` for `Glu`, `CSHLORIDE` for `CHLORIDE`. Those are now
aliases, because they are what the page actually produces.

**Consequence:** AARC needs only the encephalopathy grade, not lactate. And the general rule:
*ask the document what is in it before deciding what to look for.*

---

## D13 — ABG electrolytes are not serum electrolytes

**Decided:** blood-gas analytes carry an `abg_` prefix and are never merged with their
laboratory equivalents.

**Forced by:** the ABG panel reports its own `Na+`, `K+`, `Cl-`, `Ca++` and `Hct`, measured on
a different specimen by a different method with different reference ranges. MELD 3.0 requires
the **serum** sodium.

Silently merging the two would have fed a bedside point-of-care sodium into a transplant
priority score — the sort of error that produces a confident, wrong number. The same
confusion, going the other way, is what filed a blood-gas haematocrit as a serum PCV (D11).
