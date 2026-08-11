# The reusable prompt — point this pipeline at another report

This is the specification, written as a brief. Hand it to a capable agent (or a person)
along with a new scanned laboratory PDF and it should reproduce this pipeline for that
document.

Everything in it was learned by building the pipeline. The traps listed are real ones that
were hit, not hypotheticals; `docs/OCR-NOTES.md` holds the measurements behind each. Every
number used as an example below comes from the synthetic case in
`tools/make_synthetic.py`.

---

## The brief

> Build an **offline** pipeline that turns a scanned laboratory-report PDF into a verified,
> per-analyte time series, and renders it as a dashboard that answers, in one screen each:
> *is the patient getting better or worse*, *what changed today*, *what do these numbers
> mean in plain English*, and *what should the doctor look at*.
>
> Every charted number must be traceable to the pixels it was read from.

## Non-negotiables

1. **The document is PHI. Nothing leaves the machine.** No cloud OCR, no hosted LLM API, no
   CDN, no web font, no analytics. If a chat feature is wanted, it runs against a local
   model server bound to `127.0.0.1`.
2. **Containment before data.** Write `.gitignore`, the pre-commit identifier guard and the
   run-time refusal *before* the PDF is copied anywhere near the repo. Verify the guard by
   trying to commit a file containing an identifier and watching it fail. See `PRIVACY.md`
   — including the quasi-identifier layer, which is the one that decides whether the
   repository is actually anonymous.
3. **Never fabricate a clinical input.** A score that needs a bedside finding the labs do
   not contain reports `complete: false` and names what is missing. A default is a lie with
   a number attached.
4. **No formula from memory.** Cite every coefficient to a source and record the citation.
   Re-verify against the primary source; a plausible-looking coefficient is the most
   dangerous thing in the codebase.
5. **The export gate is code, not discipline.** The build refuses to emit while a charted
   value is unverified.

## Stage 0 — containment, before the document exists on disk

In this order, and none of it later:

| Step | Verified by |
|---|---|
| `.gitignore` covers the data and output directories, every document/image extension, OCR intermediates, and every *copy* pattern (`*.bak`, `*copy*`, `*backup*`) | `git check-ignore -v data/ dist/` prints a matching rule for each |
| Run-time refusal: the entry point exits if those directories are not ignored | delete a line from `.gitignore`, run it, watch it refuse |
| Pre-commit identifier guard installed | a deliberate failing commit |
| Denylist of identifiers, quasi-identifiers and real values, held **outside** the tree | the scanner loads it and refuses to run without it |

Only then copy the PDF in.

## Method

### Stage 1 — ask the document what is in it

Do this **before** writing the analyte dictionary. Run a cheap OCR pass over every page and
build a frequency list of label-like tokens.

> The single most expensive mistake available here is deciding what the document contains.
> A keyword sweep for `LACTATE` found nothing and it was recorded as unavailable. The
> blood-gas analyser prints it as `Lac`, on 13 pages, elevated. The same assumption hid an
> entire arterial blood gas panel — about a sixth of the document.

The scan also hands you the OCR corruption list for free (`Het`→`Hct`, `Nat`→`Na+`,
`cI-`→`Cl-`). Those become aliases, because they are what the page actually produces.

Expect a scanned report to have **no text layer at all**. On the development document,
`pdftotext -layout` over 112 pages returned 112 characters — one form feed per page. Every
number therefore comes out of an image, which is why validation is a larger part of this
project than extraction is.

### Stage 2 — find the structure geometrically, before reading any text

Profile row luminance to locate filled bands (column headers, sample metadata). No numpy
needed: collapsing the page to a single column of pixels with ImageMagick makes each output
pixel the mean of one image row.

Separate bands from body text by **height and darkness together**:

| Region | Height (px) | Mean luminance |
|---|---|---|
| column header band | ~72 | 81 |
| sample metadata band | ~62 | 127 |
| body text lines | 14–27 | 170–191 |

Darkness alone **does not** work — a dense italic `Comments:` paragraph reads as a run of
dark rows, and the first classifier paired consecutive text lines into phantom bands.

Whatever carries the **collection timestamp** is the load-bearing element: it is the axis
every chart is drawn against, and if it is light-on-dark, default OCR drops it silently on
every page. On the development document a sweep for the sample-band label across all pages
matched **zero times** — plausible values, no clock, no error.

Read that band by inverting the strip and taking one field at a time, in its own narrow
x-window, with **no character whitelist** (the window contains the field label). Four
things had to be right, each found by a failing attempt:

| Problem | Symptom | Fix |
|---|---|---|
| Crop padded above/below | `--psm 7` returns empty — it sees two lines | crop tight to the band |
| Band read as one wide strip | worked on 7 of 55 bands | read one field at a time |
| Digit whitelist on those windows | empty | no whitelist — the window contains the label |
| Window runs to the page edge | empty | stay inside the printed band; the margin inverts to a black slab |

No single `--psm` reads every field, so try combinations in order until each field parses,
preferring a reading that contains a clock time. **47 of 55 bands read automatically**; the
rest were read by eye and recorded as overrides.

Also read the *column header* band for its **x positions rather than its text**. That gives
per-page column boundaries, which is what makes parsing survive page skew.

### Stage 3 — parse by geometry, never by line

Cluster OCR word boxes into lines by y-overlap, assign columns by x, then rejoin wrapped
names and units: a TEST-column line with no RESULT-column word belongs to the row above.

Line- or keyword-based parsing mispairs values with analyte names when a name wraps — an
error that is well-formed, plausible and wrong, which is the worst kind here. Real example:
an analyte printed as `ABSOLUTE BASOPHIL` / `COUNT` with its unit as `10^3/mm^` / `3`.

Carry sample context forward onto continuation pages. **58 of 112 pages had no band of
their own** — without that rule half the document contributes values with no timestamp.

Expect physical damage to eat characters: a punch hole turned `PROTHROMBIN TIME` into
`>ROTHROMBIN TIME`, which matches no alias exactly. A `difflib` similarity fallback with a
**high** cutoff (0.86) recovers it. Keep the cutoff high deliberately: mapping a value onto
the *wrong* analyte is far worse than dropping it, because a dropped value shows up in the
coverage count and a mismapped one does not.

### Stage 4 — read every value more than once, differently

Multiple OCR passes with **decorrelated preprocessing**, then vote:

| Pass | Settings | Decorrelated by |
|---|---|---|
| A | `--psm 6`, greyscale | baseline |
| B | `--psm 4`, Otsu threshold | different segmentation assumption **and** different binarisation |
| C | `--psm 6`, greyscale, numeric character whitelist | cannot emit a letter at all, by construction |

Apply the digit whitelist to the **value box only**.

> Pass C was silently dead for the first implementation. It was configured as a whole-page
> read with a digit whitelist — which destroys every analyte name on the page, so the
> geometric parser matched no rows and pass C returned `None` for all 471 values. The
> ensemble was quietly running on two passes, and the contact sheets showed it as a column
> of `None` that nobody had been asked to look at.

Applied to the value box, where the region contains only a number, the whitelist makes
`O`/`0`, `l`/`1`, `S`/`5`, `B`/`8` confusion impossible by construction. Re-reading every
value from its own bounding box gave **444 agree, 27 disagree, 0 unreadable**.

Keep every reading. A value three passes agree on is worth more than the same value from
one, and the disagreements are exactly the list a human must look at.

### Stage 4b — resolve the decimal shift, and only that

All 27 disagreements were the same failure: a lost decimal turning `2.1` into `21.0`. Two
resolvers, in order:

1. **The printed reference range.** One candidate sits inside it, the other an order of
   magnitude outside. Uses the lab's own printed range; no clinical judgement.
2. **The analyte's own distribution.** Carboxyhaemoglobin reads 1.4, 1.6, 1.5, 1.3 across
   the document, so a `15.0` is not a sick patient, it is a missing decimal.

Resolver 2 fires **only** when an alternative reading sits near the median *and* the chosen
value is 5× away, so genuinely extreme values are untouched — the synthetic case has a
bilirubin of 18.0 mg/dL against a 1.2 ceiling, 15× out, and nothing may touch it.

### Stage 5 — validate against things that are true regardless of illness

Four gates, independent rather than sequential — which gate a value fails is itself
diagnostic:

1. **Ensemble agreement** across passes. Two-to-one is not a pass; it is a coin toss with
   extra steps.
2. **The printed H/L flag**, cross-checked against the parsed reference range. The lab has
   already published a redundant encoding of every value's position.
3. **Arithmetic identities the analyser guarantees** — `INR ≈ (PT/MNPT)^ISI`,
   `total bilirubin = direct + indirect`, `MCV = PCV/RBC×10`, `MCHC = Hb/PCV×100`,
   `absolute count = TLC × diff%/100 × 1000`, differential sums, `NLR = ANC/ALC`.
4. **A physiological envelope**, kept wide — "no human has ever had this", not a reference
   range.

Gate results need three states, not two: `pass`, `fail:<reason>`, and `skip:<reason>`.
**A skip is not a pass.** An identity that never ran because a partner value was missing
contributed no assurance and must not look like one that did.

> **Prefer identities to plausibility.** A severely ill patient's real values look
> implausible; a validator tuned to flag them flags the clinical signal and teaches the
> team to click past it — including the day it is right. Identities hold no matter how sick
> the patient is, so a violation is *always* an extraction error, never an ambiguous one.

Worked example, on the synthetic case. The page prints, on one sample:

```
PROTHROMBIN TIME                38.2  s
MEAN NORMAL PROTHROMBIN TIME    12.0  s
INR                              3.18
```

```
predicted INR      = (38.2 / 12.0) ^ 1.0 = 3.1833
relative deviation = |3.1833 - 3.18| / 3.18 = 0.0033 / 3.18 = 0.0010  ->  0.10%
0.10% < 6% tolerance  ->  pass:inr_from_pt
```

Three independently extracted numbers, from three separate cells on a scanned page,
reconcile to 0.1%. That is evidence the geometric parser paired each value with the right
analyte — the failure a keyword parser produces and cannot detect.

Now the corruption the layering exists for. OCR drops the decimal one place, `38.2` → `3.82`:

| Gate | Result |
|---|---|
| flag consistency | `3.82 < 10.8` → derived L; the page printed H → `fail:flag_mismatch` |
| envelope | PT envelope `5–250 s`; `3.82 < 5` → `fail:envelope` |
| arithmetic | predicted INR `3.82/12.0 = 0.318` against a printed `3.18` → 90% miss → `fail:inr_from_pt` |

One dropped decimal, three independent alarms, and a PT of 3.82 s is a value no reader
blinks at in isolation. Meanwhile the *correct* PT of 38.2 s — wildly abnormal — passes
every gate, which is the envelope working as designed.

Keep the identity tolerance loose (6%). The analyser rounds its printed values, and the
thromboplastin ISI is a property of the reagent lot that the report does not print. An
alarm that fires on rounding is an alarm nobody reads.

On failure: keep the value, flag it, preserve every candidate reading and the crop path,
and queue **every member** of a failed identity — the identity says the set is
inconsistent, not which member is wrong, and guessing is how a good value gets "corrected"
into a bad one. Never drop it: a dropped value is an invisible gap in a trend line.

### Stage 6 — a human looks at every charted value

Generate a crop of the pixels behind each value, with enough context to identify the row,
and montage them into contact sheets **grouped by analyte** so a whole series is checked at
once. An outlier in a column of numbers is obvious in a way a single crop never is.

> This step is not ceremony. Three-pass agreement and four gates all passed on two real
> errors that only eyes caught:
>
> - **A blood-gas haematocrit filed as serum PCV.** `PCV` and `HCT` were aliased to the same
>   key, so a value from a different instrument, with a different reference range, was fed
>   into the red-cell index identities. Every glyph was read correctly; the *label* was
>   wrong.
> - **Base excess without its minus sign.** The value regex had no provision for a leading
>   `-`, and OCR sometimes separates the sign from its digits. Base excess is *routinely*
>   negative — that is how metabolic acidosis is reported — so the error inverts the
>   clinical meaning in a patient whose lactate is rising.
>
> Automated checks confirm the glyphs were read. They cannot confirm the number was filed
> under the right analyte, or that a character the parser never looked for was there.

The human step is not a re-reading of every page. The gates have already agreed on the
overwhelming majority; those get a fast confirm against the crop, and the review queue —
failures *and* skips — gets the slow one. The point of the automation is to make attention
land where it is worth spending.

Record the result as a field in the dataset, not a checkbox in someone's memory, and make
the build refuse to export while any charted value is unverified. No `--force`, no
`--skip-verification`: every escape hatch is a checklist wearing a costume, and the first
time the build blocks on a deadline the flag gets used, and after that it is always used.
The legitimate escape is to **narrow what is charted** — explicit and reviewable — never to
lower the bar for what counts as verified.

### Stage 7 — separate specimens, always

Blood-gas electrolytes are not serum electrolytes: different specimen, method and reference
range. Prefix them and never merge. A transplant-priority score computed from a bedside
point-of-care sodium is a confident wrong number. Likewise ascitic fluid albumin is not
serum albumin, and an interpretation paragraph mentioning albumin is not a result at all.

### Stage 8 — score by day, not by sample, and label carry-forward

Different analytes go into different tubes drawn hours apart. Scoring per sample reports
inputs as missing that were measured the same morning. Score per day, latest value wins,
and carry a value forward up to a stated age — naming every carried input and its age.

### Stage 9 — units are part of the value

Display the unit the analyte is *defined* with, not the one OCR read — and then check that
the definition matches the magnitudes actually being stored. Substituting a canonical
`10^3/mm^3` for a printed `cells/cumm` while the parsed values are counts per mm³ renders a
white cell count of 19,100 as **19,100 ×10³/mm³**: a thousandfold overstatement, produced by
a line of code written to improve consistency, on a page where every digit is correct.

Unit substitution must convert or refuse. It must never relabel.

### Stage 10 — two registers, one dataset

Every finding gets a plain-English sentence for family and a precise clinical line for the
doctor. Encode status by **shape and text as well as colour**. Do not inflate severity: in
a patient abnormal on every axis, marking everything critical makes the view useless.

---

## Deliverables checklist

- [ ] `.gitignore` + identifier pre-commit guard, **verified by a failing commit**
- [ ] A denylist covering identifiers, quasi-identifiers and real values, held outside the tree
- [ ] Analyte dictionary built from a scan of the document, with observed OCR variants
- [ ] Timestamp recovery with coverage reported as a number
- [ ] Geometric parser with wrapped-name merge and continuation-page carry-forward
- [ ] Multi-pass OCR with per-value readings retained, and proof that every pass is alive
- [ ] Four validation gates, each with a test that fails when the gate is removed
- [ ] Evidence crops and contact sheets, grouped by analyte
- [ ] Human verification ledger, and a build that refuses to export without it
- [ ] Scores with cited coefficients and honest `complete: false`
- [ ] Self-contained dashboard, zero network requests, verified in a browser
- [ ] A synthetic dataset, so the thing can be demonstrated without the document
- [ ] `DECISIONS.md` recording what was decided, what forced it, and what was got wrong

## Report honestly

State coverage as counts, not adjectives. Say which values are verified and which are not.
Say what the document does not contain. If a score cannot be computed, say why — and never
default the input to make it computable.
