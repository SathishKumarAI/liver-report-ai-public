# Validation — the four gates, the human check, and the build block

Owns: what each gate checks, the exact error it exists to catch, a worked example, and what
happens on failure.

Does NOT own: how OCR produces the candidate values (`docs/OCR-NOTES.md`), or the record
shape the gate results are written into (`docs/SCHEMA.md`).

**Why this document is disproportionately large:** there is no digital text in the source
PDF. `pdftotext -layout` over all 112 pages returns 112 characters (`docs/DECISIONS.md` D1).
Every number in the dataset came out of an image. There is no second source of truth to fall
back on, so the checking has to be the second source of truth.

> Worked examples use the synthetic case (`docs/SYNTHETIC-DATA.md`). The arithmetic in them
> is real arithmetic — recompute it and it holds.

---

## At a glance

Each observation carries `provenance.gates` with one entry per gate that ran
(`docs/SCHEMA.md`). They are independent, not a pipeline — a value can fail one and pass the
others, and which ones it fails is itself diagnostic.

| # | Gate | Question it asks | Catches |
|---|---|---|---|
| 1 | `ensemble` | Did three decorrelated OCR passes read the same characters? | Character-level misreads: `O`/`0`, `S`/`5`, `1`/`7`, speckle read as a decimal point |
| 2 | `flag_consistency` | Does the parsed value sit where the lab's printed ▲(H)/▼(L) flag says it sits? | **Decimal-point placement and digit drop** — the order-of-magnitude errors |
| 3 | `arithmetic` | Do the analyser's own algebraic identities still hold? | Any single corrupted member of a related set, including ones that look entirely plausible |
| 3b | `differential` | Do the white-cell percentages still sum to ~100? | A digit error anywhere in the differential, when no other identity covers it |
| 4 | `envelope` | Is the value inside the physiologically possible range for that analyte? | Gross corruption: a stray digit, a merged cell, an analyte↔value mispairing |
| — | human | Does the crop show what the record says? | Everything the gates missed, including correct-but-mispaired values |
| — | build | Is any charted value still unverified? | Discipline failure — the check that was *supposed* to happen |

Every gate returns `{"state": …, "detail": …}`. The state vocabulary:

| State | Meaning |
|---|---|
| `pass` | ran, passed. `detail` names the identity where one applied |
| `weak` | ran, did not certify — a bare majority, a single voting pass, a value that reads abnormal with no flag printed. **Not a pass.** Sets `needs_review` |
| `fail` | ran, failed. Blocks `human_verified` from being auto-set; routes to the review queue |
| `skip` | could not run — no value, no usable reference range, no partner value. **Never silently `pass`** |

`needs_review` is true if any gate is `fail` **or** `weak`. Three skips and one pass means
one gate stood behind that number, and the review queue should say so.

---

## Why arithmetic identities, not plausibility checks

This is the load-bearing design decision of the whole validation phase
(`docs/DECISIONS.md` D8), so it is stated in full here.

The obvious way to validate an extracted lab value is to ask "is this plausible?" — is the
INR in a believable range, is the procalcitonin something a person could have. **That
approach fights this dataset.**

| | Plausibility check | Arithmetic identity |
|---|---|---|
| What it asserts | "a patient's value is usually near X" | "the analyser computed A from B and C, so `A = f(B, C)`" |
| Holds when the patient is critically ill? | **No.** In acute-on-chronic liver failure a correctly extracted INR of 2.51 and procalcitonin of 4.11 are ordinary findings, and both are far outside any plausible band | **Yes.** `MCV = PCV/RBC × 10` is true at an MCV of 60 and at an MCV of 130. Illness does not repeal arithmetic |
| What a violation means | Ambiguous: sick patient, or bad extraction? | Unambiguous: **bad extraction.** The analyser did not print an inconsistent set |
| Failure mode of the check itself | Fires on the true clinical signal. The alarm becomes noise, and the first thing a team does with a noisy alarm is learn to dismiss it — including the day it is right | Fires only on corruption. Silent when the data is good, however alarming the data is |

The whole point of this dashboard is a patient whose values are extreme. A validator tuned
to flag extreme values would flag the entire clinical picture and teach us to click past it.
So:

- **Gate 3 (arithmetic) is the primary gate.** It is the only one that is both sensitive and
  specific on this data.
- **Gate 4 (envelope) is deliberately crude.** Its bounds (`config.ANALYTES[…].lo/hi`) are
  physiological limits — "no human has ever had this" — not reference ranges. `pt` runs
  `5–250 s`; a PT of 30.1 s is wildly abnormal and comfortably inside. That is intended.
- **No gate anywhere compares a value to its clinical reference range to decide whether it
  is real.** The reference range is used only by gate 2, and only to check agreement with
  what the page itself printed.

The report supplies one of these bounds itself: *"the differential count is computed from a
total of several thousands of cells… may not add upto exactly 100. It may fall between 99
and 101."* `config.DIFFERENTIAL_SUM_RANGE` widens that to `(97.0, 103.0)`, because the gate
exists to catch a digit error, not to audit the analyser's cell counting.

---

## Gate 1 — `ensemble`: three OCR passes must agree

**Checks.** Each value region is read three times with deliberately decorrelated settings
(`config.OCR_PASSES`):

| Pass | Settings | Decorrelated by |
|---|---|---|
| A | `--psm 6`, greyscale | baseline |
| B | `--psm 4`, Otsu threshold | different page-segmentation assumption **and** different binarisation |
| C | `--psm 6`, greyscale, `tessedit_char_whitelist=0123456789.<>-+` | cannot emit a letter at all, by construction |

Per-word confidence below `config.MIN_WORD_CONF = 55` is treated as a non-vote.

**The exact failure it catches.** Single-character substitution — Tesseract's classic
confusions `O`→`0`, `S`→`5`, `1`→`7`, `,`→`.`, plus scanner speckle read as a decimal point.
Pass C is the specific answer to letter-for-digit substitution: with a numeric whitelist `O`
is not in the output alphabet, so if A reads `2.5l` and C reads `2.51`, the disagreement
localises the fault to the character rather than to the value.

**Worked example.** Page 34, the INR cell. `provenance.ocr` records
`{"A": 2.51, "B": 2.51, "C": 2.51}` — three passes, one distinct value, `pass: unanimous`.

Contrast the corruption this gate is built for: `A: 2.51`, `B: 2.51`, `C: 251` — pass C,
restricted to digits and punctuation, lost a faint decimal point rather than hallucinating
one. Two-to-one is **not** a pass. It records `weak: majority 2.51 of [2.51, 251]`, which
sets `needs_review` and sends the value to a human, because a majority vote of three passes
over a two-in-a-thousand event is not evidence, it is a coin toss with extra steps.

**Where this gate was itself broken.** For an entire extraction run pass C returned `None`
for all 471 values — the whitelist had been applied to the whole page, which destroys every
analyte name and leaves the geometric parser nothing to match (`docs/OCR-NOTES.md` §6). The
gate reported `pass` throughout, because two agreeing passes and one abstention are
indistinguishable from unanimity unless the voters are counted. A configured pass returning
nothing is now a fault, not an abstention.

**On failure.** `gates.ensemble.state = "fail"`, `human_verified: false`, all three candidate
readings preserved in `provenance.ocr`, and a crop path. The observation goes to the review
queue. It is **not** dropped — a dropped value is an invisible gap in a trend line, which is
worse than a flagged one.

---

## Gate 2 — `flag_consistency`: the value must agree with the flag the lab printed

**Checks.** The lab prints, next to most values, its own interpretation: `▲ (H)`, `▼ (L)`,
`(CH)` for critical high. This maps one-to-one onto the FHIR `interpretation` code set, so
the report has published a **redundant encoding of every value's position relative to its
own reference range**. The gate recomputes that position from the parsed value and the
parsed reference range, and requires the two to match. `CH`/`CL` are mapped to FHIR `HH`/`LL`
at this point — without that, nothing in the dataset ever carries a critical code and a
doctor view filtering on `HH` prints "no critical values" on the same page as a critical
ammonia.

**The exact failure it catches.** Decimal-point placement and digit drop — the two OCR
faults that do the most clinical damage, because they move a number by an order of magnitude
while leaving it looking like a perfectly reasonable lab value (`docs/DECISIONS.md` D7). No
clinical knowledge is needed to catch them, only consistency.

**Worked example.**

```
Printed:   PROTHROMBIN TIME   30.1  ▲ (H)   10.8 - 13.2
Parsed:    pt = 30.1, reference {low: 10.8, high: 13.2}, printed_flag "H"
Derived:   30.1 > 13.2  ->  H
Compare:   H == H  ->  pass
```

Now the corruption. Suppose OCR drops the decimal one place and reads `3.01`:

```
Parsed:    pt = 3.01
Derived:   3.01 < 10.8  ->  L
Printed:   H
Compare:   L != H  ->  fail
```

A PT of 3.01 s is a value no reader would blink at in isolation. The page itself refuses it.
Note what happens to the *other* gates on that same corrupted value:

| Gate | On `pt = 3.01` |
|---|---|
| 4 envelope | `pt` envelope is `5–250 s`; `3.01 < 5` → **fail** |
| 3 arithmetic | `inr_from_pt`: `3.01 / 12.0 = 0.2508` against a printed INR of `2.51` — a 90% miss → **fail** |

One dropped decimal, three independent alarms. The layering is the design.

**On failure.** `gates.flag_consistency.state = "fail"`, queued for human review with the
crop. Where the page prints no flag and the value reads normal, `pass`. Where the page prints
no flag but the value reads `H` or `L`, `weak` — the disagreement might be a missing flag or
a misread value, and the gate says so instead of choosing. Where there is no usable printed
range at all, `skip`: it does not invent an interpretation and does not report a pass it did
not earn.

---

## Gate 3 — `arithmetic`: the analyser's own identities must still hold

**Checks.** Every identity in `validate.IDENTITIES` whose members are all present on the
same sample, compared with a relative tolerance of `config.REL_TOLERANCE = 0.06` (6%):

| Identity | Applies to |
|---|---|
| `INR ≈ (PT / MNPT)^ISI`, `config.INR_ISI = 1.0` | coagulation panel |
| `bilirubin_total = direct + indirect` | LFT panel |
| `protein_total = albumin + globulin`, `A:G = albumin / globulin` | LFT panel |
| `MCV = PCV / RBC × 10`, `MCH = Hb / RBC × 10`, `MCHC = Hb / PCV × 100` | CBC red-cell indices |
| `NLR = ANC / ALC` | CBC differential |
| differential percentages sum within `config.DIFFERENTIAL_SUM_RANGE = (97.0, 103.0)` | CBC differential, reported under its own `differential` key |

**The exact failure it catches.** One corrupted member of a set whose other members are
intact — including corruptions that are entirely plausible on their own and that gates 1, 2
and 4 all wave through.

**Worked example — the corruption only this gate sees.** Synthetic day 1 prints
`Hb 11.8 g/dL` (ref `13.0 - 17.0`), `RBC 3.42`, `PCV 34.1`, `MCH 34.5`, `MCHC 34.6`. Suppose
OCR reads the haemoglobin as `1.8`:

| Gate | Verdict on `hemoglobin = 1.8` | Why |
|---|---|---|
| 2 flag_consistency | **pass** | `1.8 < 13.0` → `L`, and the page printed `L` for the true value too |
| 4 envelope | **pass** | `hemoglobin` envelope is `1.5 – 25`; `1.8` is inside it |
| 3 arithmetic | **fail** | `MCH = 1.8 / 3.42 × 10 = 5.26` against a printed `34.5` — an 85% miss. `MCHC = 1.8 / 34.1 × 100 = 5.28` against `34.6` fails identically |

A haemoglobin of 1.8 g/dL is survivable-on-paper and internally consistent with its own flag.
Only the indices printed beside it know it is wrong.

**Worked example — the identity that was hand-checked before any code was written.**

Page 34, one sample:

```
PROTHROMBIN TIME                30.1  s
MEAN NORMAL PROTHROMBIN TIME    12.0  s
INR                              2.51
```

```
predicted INR = (PT / MNPT) ^ ISI
              = (30.1 / 12.0) ^ 1.0
              = 2.50833

relative deviation = |2.50833 - 2.51| / 2.51
                   = 0.00167 / 2.51
                   = 0.00066   ->  0.07%

0.07% < 6.0% tolerance   ->  pass
detail: "inr_from_pt: expected 2.508, page says 2.51"
```

Three independently extracted numbers, from three separate cells on a scanned page,
reconcile. That is evidence the geometry-based parser paired each value with the right
analyte — the failure mode a keyword parser produces and cannot detect
(`docs/DECISIONS.md` D3).

**Why 6% and not tighter.** The tolerance is deliberately loose, for two real reasons. The
analyser rounds its printed values — a total protein printed to one decimal cannot reconcile
exactly with two components also rounded to one decimal — and `INR_ISI = 1.0` is an
**assumption**: the true ISI belongs to the thromboplastin reagent lot and is not printed on
the report. A residual of a percent or so is therefore expected and is evidence about the
reagent, not about the extraction. A tight tolerance would fire on rounding, and an alarm
that fires on rounding is an alarm nobody reads. If the ISI is ever obtained from the lab it
goes in `config.INR_ISI` and this gate sharpens for free.

**Worked example — the differential sum.** Day 7: `89.6 + 5.2 + 4.8 + 0.3 + 0.1 = 100.0`,
inside `97–103` → `pass`. Read the neutrophil percentage as `39.6` and the sum is `50.0` →
`fail: differential sums to 50.0, outside 97.0-103.0`, on every member of the differential.

**On failure.** `state: "fail"` with the identity named and both the predicted and printed
values in `detail`, and **every member of the set** queued for review — not only the one
that looks wrong. The identity says the set is inconsistent; it does not say which member is
at fault, and guessing at that is how a good value gets "corrected" into a bad one.

Where a member is absent the identity does not run and writes nothing. An identity that
never ran contributed no assurance and must not look like one that did.

---

## Gate 4 — `envelope`: the value must be physiologically possible

**Checks.** The parsed value lies within `config.ANALYTES[key]["lo"]`–`["hi"]`. These are
**not reference ranges.** The comment in `config.py` states it directly: *"a value outside
this is an extraction error, not a sick patient."*

| Analyte | Envelope | Reference range |
|---|---|---|
| `pt` | 5 – 250 s | 10.8 – 13.2 s (~20× wider) |
| `inr` | 0.5 – 15 | < 1.3 |
| `bilirubin_total` | 0.05 – 60 mg/dL | 0.3 – 1.2 mg/dL |
| `hemoglobin` | 1.5 – 25 g/dL | 13.0 – 17.0 g/dL |
| `wbc` | 50 – 200 000 cells/cumm | 4 000 – 10 000 cells/cumm |

The `wbc` row is there because it was wrong: the envelope and the declared display unit
disagreed about scale by a factor of 1000 and neither noticed the other
(`docs/SCHEMA.md`). Envelope and unit are one statement in two fields and are edited
together.

**The exact failure it catches.** Gross corruption that survives the other gates: a stray
digit appended, two adjacent table cells merged into one token, or an analyte↔value
mispairing that lands a haemoglobin in a bilirubin row. It is the cheap backstop, not the
primary defence.

**Worked example.** `pt = 30.1` against envelope `5–250` → `pass`. Severely abnormal;
comfortably inside. **This is the gate working correctly** — a validator that flagged a PT of
30.1 as suspicious would be flagging the reason this dashboard exists.

The corruption it is for: the decimal is lost rather than moved and `30.1` reads as `301` →
`301 > 250` → `fail`. In the other direction the same fault gives `3.01 < 5` → `fail`, the
same dropped decimal gate 2 caught, caught again by an unrelated mechanism.

**On failure.** `state: "fail"`, `detail` naming the bound crossed, queued for review. An
envelope failure is close to a guaranteed extraction error, so these sort to the top of the
queue.

---

## The human verification step

Four automated gates cannot certify a number, because all four can be satisfied by a value
that is correct in isolation and attached to the wrong analyte, the wrong sample, or the
wrong day. A haemoglobin of 11.8 is a perfectly good haemoglobin whichever row it is printed
in.

**The step.** For every observation that reaches a chart, a human opens `provenance.crop` —
the actual pixels the number came from, cropped at `provenance.bbox` on `provenance.page` —
and confirms three things:

| Confirm | Against |
|---|---|
| The number matches | the crop |
| The analyte matches | the row label in the crop (which is why the crop reaches left across the name, not just the digits) |
| The timestamp matches | the sample band this page inherits (`docs/DECISIONS.md` D4) |

Only then is `provenance.human_verified` set to `true`.

**Two errors that reached this step with every gate green** (`docs/OCR-NOTES.md` §8): a
blood-gas haematocrit filed as a serum PCV, and a base excess recorded without its minus
sign. Neither is detectable by agreement — the first was read perfectly and labelled wrongly,
and the second was a character the parser never looked for, so there was nothing for the
passes to disagree about.

**What it is not.** It is not a re-reading of every value on 112 pages. The gates have
already agreed on the overwhelming majority; those get a fast confirm against the contact
sheet. The review queue — the failures, the `weak`s and the `skip`s — gets the slow one. The
purpose of the automation is to make the human's attention land where it is worth spending.

**The recorded state is the whole point.** `human_verified` is a field in the dataset, not a
checkbox in someone's memory, which is what makes the next section possible.

---

## The build gate

`build.py` **refuses to emit the dashboard** while any charted observation has
`provenance.human_verified: false`. It exits non-zero and prints, for each offender: the
analyte, the day, the page number and the crop path — the four things needed to go and check
it.

**Why it is code and not a checklist.** The requirement is *no wrong data points.* A
checklist that is *supposed* to be completed is not a control; it is an intention. Making the
build fail is a control (`docs/DECISIONS.md` D11). There is no `--force`, no
`--skip-verification` and no environment variable, because every one of those is a checklist
wearing a costume: the first time the build blocks on a deadline the flag gets used, and
after that it is always used.

| State | Result |
|---|---|
| Every charted value verified | Dashboard builds |
| Any charted value unverified | **Build fails**, offenders listed with crop paths |
| A value failed a gate and a human confirmed the printed page really says that | Verified; the gate failure is retained in `provenance` — the audit trail keeps the disagreement |
| A value cannot be resolved | Leave it unverified and remove it from the charted set explicitly. It stays in the dataset with its gate results, visible as a gap in the trend, labelled unresolved. **Never** silently verified to unblock a build |

The last row is the one that matters. The escape hatch from a blocked build is to *narrow
what is charted* — an explicit, reviewable act — never to *lower the bar for what counts as
verified*.

---

## What none of this catches

Stated so nobody mistakes four gates and a build block for a guarantee.

| Blind spot | Mitigation |
|---|---|
| A value correctly read but attached to the wrong analyte, where no identity involves it and no flag contradicts it | The human step, which checks the row label. This is precisely the blood-gas-Hct error, and precisely why the crop shows context |
| A sign the parser never looked for | Nothing automated. Found by reading crops; the regex now accepts a leading `-`, which fixes that one character and no other |
| A whole panel assigned the wrong timestamp, because a page inherited the wrong sample band | Sample-band extraction is validated separately (`docs/OCR-NOTES.md` §3); the flowsheet makes a mis-dated panel visible as a break in an otherwise smooth trend |
| A value the report never printed | Nothing can recover it. It renders as a gap. It is **never** interpolated, and a missing score input is never defaulted (`docs/DECISIONS.md` D9) |
| An analyser error — the lab printed a wrong number | Out of scope entirely. This pipeline validates the fidelity of extraction, not the correctness of the laboratory. If a value is clinically impossible the answer is to repeat the test, not to debug this code |
| A coefficient error in a score formula | **Not covered by these gates at all.** Covered only by transcription against the cited sources in `src/scores.py` (`FORMULA_DOCS[…]["source"]`) and by the test that asserts the published formula string matches the code's own docstring character for character |
