# Prior art — what exists, what this borrows, what it rejects

Done before writing parser code, so as little as possible was reinvented. The
constraint that decides most of it: **the source document is patient health
information and may not leave the machine.** That single rule eliminates most of
the popular tooling, which is cloud-API-backed.

## Document extraction

| Project | What it does | Verdict |
|---|---|---|
| [AHMEDELZARIA/lab-result-extraction](https://github.com/AHMEDELZARIA/lab-result-extraction) | Closest in intent: an API that pulls structured patient data out of medical PDFs | **Reject.** Built on LlamaParse — the document is uploaded to a cloud service. Precisely what must not happen. |
| [opendatalab/PDF-Extract-Kit](https://github.com/opendatalab/PDF-Extract-Kit) | Layout detection, formula and table recognition, OCR | **Reject for now.** Torch plus model weights, GPU-oriented. Heavy for a single-patient job, and this layout is regular enough that geometry beats a learned layout model. |
| [CatchTheTornado/text-extract-api](https://github.com/CatchTheTornado/text-extract-api) | Document → JSON/Markdown, with a PII-removal feature | **Reject.** Requires Ollama plus a served model. Its anonymisation idea is good, but never moving the file is stronger than redacting it afterwards. |
| [opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf) | pip-installable, emits **JSON with bounding boxes** | **Borrow the idea, not the dependency.** Bounding boxes as first-class output is exactly right — it is what makes a value auditable back to the page. `tesseract --tsv` gives the same at zero cost. |
| [sahithottikunta/pdf_ocr_extraction](https://github.com/sahithottikunta/pdf_ocr_extraction) | Tesseract plus Python, keyword-driven JSON | **Reject the method.** Keyword and line-regex extraction is the approach that breaks on scanned lab reports: names and units wrap across lines, so the value on a line often belongs to the analyte named on the line above. Geometry is required. |

**Net:** no existing project fits an offline, single-patient, audit-grade job.
This one is built, but the good ideas are taken: bounding boxes as primary
output, and per-word confidence.

## Data model — the one real borrow

[FHIR R4 `Observation`](https://hl7.org/fhir/R4/observation.html) is the
international standard for exactly what this produces: one measured value, at
one time, for one patient, with units and a reference range. Records are modelled
on it rather than inventing a shape.

Why bother when nothing here talks to a FHIR server:

- The schema questions are already answered by people who do this professionally
  — where the unit goes, how a reference range with only an upper bound is
  expressed, how a non-numeric result coexists with a numeric one.
- [`interpretation`](https://build.fhir.org/valueset-observation-interpretation.html)
  is a standard code set — `H`, `L`, `HH`, `LL`, `N`, `A` — and a lab report
  already prints exactly this information as `▲ (H)` and `(CH)`. The mapping is
  one-to-one, so **validation gate 2 is really "does the parsed value agree with
  the interpretation code the laboratory printed"**. Free redundancy from a
  standard.
- If the data ever needs to enter a real record system, it is already the right
  shape.

It is extended with one non-standard block, `provenance`, carrying page number,
bounding box, the OCR passes and the verification state. Standard where a
standard exists; custom only where nothing covers it, since no standard
describes "which pixels did this number come from".

## Clinical scoring

Formulas are taken from published sources and cited in `docs/CLINICAL.md`, never
from memory. **A recalled coefficient in a medical dashboard is an unacceptable
failure mode** — and this project has the scar to prove it: an early generated
draft of `CLINICAL.md` stated the MELD 3.0 albumin × creatinine coefficient as
−1.72. The correct value is **−1.83**. The code was right and the document was
wrong, which is the harder direction to catch.

| Score | Source | Status |
|---|---|---|
| MELD 3.0 | Kim et al., *Gastroenterology* 2021; [MDCalc](https://www.mdcalc.com/calc/78/meld-score-model-end-stage-liver-disease-12-older); [UW Hepatitis B Online](https://www.hepatitisb.uw.edu/page/clinical-calculators/meld) | Computable. Albumin × creatinine interaction term verified as **−1.83** |
| MELD-Na | [MDCalc MELD-Na](https://www.mdcalc.com/calc/1754/meldna-meld-na-score-liver-cirrhosis) | Computable. `MELD-Na = MELD + 1.32(137−Na) − 0.033·MELD·(137−Na)`, applied only when MELD(i) > 11, sodium clamped 125–137 |
| Child-Pugh | standard | **Incomplete by design** — needs ascites and encephalopathy grade, which are bedside findings |
| AARC (APASL) | [Hepatology International](https://link.springer.com/article/10.1007/s12072-017-9816-z); cut-points via [PMC8579631](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8579631/) | **Incomplete by design** — needs an encephalopathy grade. Note it was derived on serum lactate while a blood-gas lactate is what these reports carry; the result says so on its face |
| Maddrey DF | [MDCalc](https://www.mdcalc.com/calc/40/maddreys-discriminant-function-alcoholic-hepatitis) | Computable; DF ≥ 32 defines severe alcoholic hepatitis, with the aetiology caveat in `docs/CLINICAL.md` |

**Rejected:** building a mortality prediction model. AARC-AI style work exists,
but a model fitted elsewhere, applied to one patient, and presented to a worried
family is not something this tool should do.

## Dashboards

The FHIR visualisation projects surveyed —
[fhir-server-dashboard](https://github.com/smart-on-fhir/fhir-server-dashboard),
[UPR-Doctor-Dashboard](https://github.com/siddhantbhatia/UPR-Doctor-Dashboard),
[CardinalKit SMART-on-FHIR](https://github.com/CardinalKit/CardinalKit-SMART-on-FHIR)
— all assume a FHIR server plus a React/Node build. The requirement here is a
file that opens by double-click on a relative's laptop with no internet.

**Reject the stack, borrow the convention.** The clinical flowsheet — analytes
as rows, time as columns, deltas inline — is how every hospital system presents
this, and the doctor view follows it because that is what a clinician can read
without being taught.

Charting is hand-written inline SVG for the main dashboard. Not a preference for
reinvention: a charting library from a CDN is a network request, and a network
request from a page displaying patient data is a policy violation. The charts
needed — a sparkline with a shaded reference band, a flowsheet, a score
trajectory — are tens of lines of SVG each.

### Where a charting library *did* earn its place

A second artifact, the analyst view, uses **Plotly vendored and inlined**, never
from a CDN. It is separate from the main dashboard because the main dashboard is
handed to a family and must stay small; the analyst view has a different reader,
one interrogating the data, for whom zoom, pan and legend isolation genuinely
help.

One detail worth recording: it uses Plotly's **cartesian partial bundle**, not
the full one. That is a privacy decision rather than a size one — the full
bundle embeds live map-tile endpoints for its geo chart types, and shipping
third-party endpoints inside a page that displays patient data is a latent leak
waiting for someone to add a map trace. The cartesian bundle contains no geo
code, so the endpoints are not there to be triggered.

**Rejected for the UI:** FastAPI (the standard-library server already does the
job in about sixty lines), Streamlit (needs an install, cannot be handed to a
relative, and duplicates what Plotly already provides here) and shadcn/ui
(requires a Node build step for styling already in hand). The zero-install
single file is a feature, not a limitation.

## Techniques taken from the wider literature

- **Word-level boxes plus confidence as the parsing substrate** (`tesseract --tsv`)
  rather than reflowed text. Standard practice in document AI, and the reason
  line-based parsers fail on this material.
- **Multi-pass OCR with decorrelated preprocessing**, then agreement voting.
  Standard in archival digitisation, where a wrong digit is unacceptable.
- **Character whitelisting on numeric fields** (`tessedit_char_whitelist`), which
  makes `O`→`0` and `S`→`5` confusion impossible by construction rather than
  merely unlikely. With the important caveat recorded in `docs/OCR-NOTES.md`:
  never apply it to a region that also contains labels.
- **Contrast inversion for light-on-dark regions.** Tesseract assumes dark text
  on a light ground; a white-on-grey metadata band is the opposite, and vanishes
  entirely until inverted.
