# Clinical reference

Owns: every formula this pipeline computes, every analyte it charts, and what both mean —
once in plain words, once for a clinician.

Does NOT own: how a value is extracted (`docs/OCR-NOTES.md`), how it is checked
(`docs/VALIDATION.md`), or the dataset shape (`docs/SCHEMA.md`).

> **Every number in this file comes from the synthetic case in `tools/make_synthetic.py`.**
> That case is invented, not de-identified: no real measurement was transformed to produce
> it, so there is nothing in here to re-identify. It is clinically *shaped* — a fabricated
> acute-on-chronic liver failure over eight days — because a formula demonstrated on random
> noise proves nothing about whether the arithmetic is right.

> **Nothing in this file is a diagnosis.** It describes a lab dataset with no imaging, no
> examination and no medication record. Section C says why that matters.

Days are referred to as **day 1 … day 8**. The generator stamps them with calendar dates
purely so the date-handling code has something to parse; the day index is the real axis.

---

## A.0 — Coefficient verification checklist (READ FIRST)

Development runs offline by policy, so the coefficients in section A were originally
written **from the cited publications, not read off them in the session that wrote this
file**. A recalled coefficient in a medical dashboard is exactly the failure mode
`docs/RESEARCH.md` says is unacceptable.

**Rule: no score renders a *number* in the dashboard until its row below reads `verified`.**
Rendering a score as `complete: false` with its missing inputs named is not a number, and
is always allowed — that is what section C describes. The rule bites the moment a value
would be shown, including the moment a clinician supplies the missing bedside grade and an
unverified score becomes computable.
`src/scores.py` is expected to carry the same constants; verifying here and in code
separately is the point — two independent transcriptions that agree are evidence, one is a
guess.

**The two-transcription rule paid for itself on the first audit.** This file carried the
MELD 3.0 albumin×creatinine interaction coefficient as **−1.72**; the published value in
Kim et al. 2021 is **−1.83**. `scores.py` had −1.83 all along, so the two transcriptions
disagreed, and the disagreement is what surfaced the error. Corrected in A.1.

Note *why* it survived, because the same blind spot will hide the next one: the term is
bounded by `(3.5 − alb) ≤ 2` and `ln(Cr) ≤ ln(3)`, so the wrong coefficient moves the score
by **at most 0.24 points** — never enough to look absurd, occasionally enough to cross an
integer boundary, and MELD boundaries are what allocation is ordered by. A coefficient
error that changes the number a lot gets caught by anyone reading the output. This kind
does not. Only reading it off the source catches it. A.1 carries a worked pair that flips
30 → 31 on that one digit.

| Formula | Source to check against | Status | Risk if wrong |
|---|---|---|---|
| MELD 3.0 | Kim et al., *Gastroenterology* 2021 (primary) · [MDCalc](https://www.mdcalc.com/calc/78/meld-score-model-end-stage-liver-disease-12-older), [UW](https://www.hepatitisb.uw.edu/page/clinical-calculators/meld) | **verified** against Kim et al. 2021 — one error found and fixed (−1.72 → −1.83) | 9 coefficients + 2 interaction terms; high transcription surface |
| MELD-Na | [MDCalc](https://www.mdcalc.com/calc/78/meld-score-model-end-stage-liver-disease-12-older), [UW](https://www.hepatitisb.uw.edu/page/clinical-calculators/meld) | **verified** against MDCalc — coefficients and the `>11` guard confirmed; the one-decimal rounding of `MELD(i)` was missing here and has been added | two-stage formula; the `MELD(i) > 11` guard is easy to drop |
| Child-Pugh | [MDCalc](https://www.mdcalc.com/calc/340/child-pugh-score-chronic-liver-disease) | **unverified — check cut-points** | INR band boundary differs between published variants (see block) |
| AARC | [Hep Int](https://link.springer.com/article/10.1007/s12072-017-9816-z), [PMC8579631](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8579631/) | **unverified — check all five cut-points** | five 3-band cut-points recalled together; lowest confidence in this file |
| Maddrey DF | [MDCalc](https://www.mdcalc.com/calc/40/maddreys-discriminant-function-alcoholic-hepatitis) | **verified** against MDCalc — the 4.6 factor and the DF ≥ 32 threshold | single coefficient, low surface |
| Anion gap | [MDCalc](https://www.mdcalc.com/calc/1669/anion-gap) | definitional | which specimen, and whether K⁺ is included |
| NLR | [PubMed 36571711](https://pubmed.ncbi.nlm.nih.gov/36571711/) | definitional | none — it is a ratio |
| CBC identities | definitional (see A.8) | **no external citation and none needed** | unit scaling, not the algebra |

`PubMed 36571711` is carried from this project's source list; its title was not re-checked
offline. Cite it only for "NLR is used as a prognostic marker in liver failure", never for
a threshold.

---

## A — Formulas

Every block below gives the equation with units, what it means to a family member, what it
means to a hepatologist, and the source. Where a formula needs something a lab report
cannot contain, that is stated in the block, not hidden.

Worked examples use the synthetic case. Day 1 of that case is:

| bilirubin | direct | indirect | INR | PT | MNPT | creatinine | urea | sodium | albumin | globulin | lactate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 14.6 | 8.1 | 6.5 | 3.18 | 38.2 s | 12.0 s | 1.74 | 46 | 130 | 2.7 | 3.9 | 3.2 |

and day 8 is bilirubin 18.0, INR 2.41, creatinine 2.58, sodium 136, albumin carried
forward at 2.7. Sex is male, no renal replacement therapy.

### A.1 MELD 3.0

| | |
|---|---|
| **Equation** | `MELD3.0 = 1.33·(female) + 4.56·ln(bili) + 0.82·(137 − Na) − 0.24·(137 − Na)·ln(bili) + 9.09·ln(INR) + 11.14·ln(Cr) + 2.06·(3.5 − alb) − 1.83·(3.5 − alb)·ln(Cr) + 6` |
| **Units** | `bili` total bilirubin mg/dL · `Na` **serum** sodium mmol/L · `INR` unitless · `Cr` **serum** creatinine mg/dL · `alb` albumin g/dL · `female` = 1 if female, 0 if male (synthetic case: **0**) |
| **Bounds, applied before the logs** | bilirubin, INR, creatinine each floored at 1.0 · creatinine capped at 3.0 · albumin floored at 1.5, capped at 3.5 · sodium floored at 125, capped at 137. If the patient had ≥2 dialysis sessions or 24 h of CVVHD in the prior week, creatinine is **set to 3.0** regardless of the measured value. |
| **Output** | rounded to the nearest integer (half away from zero — banker's rounding disagrees with every published calculator at `.5`), then clamped to **6–40**. The floor of 6 matters as much as the cap. Age ≥ 12. |
| **Plain words** | A single number from 6 to 40 that sums up how badly the liver is failing. It is built from five blood tests: the yellow pigment (bilirubin), how slowly blood clots (INR), a kidney waste product (creatinine), salt level (sodium), and the liver's main protein (albumin). Higher means sicker. It is the number transplant services use to decide who is waiting in the most danger. It is a measure of *risk*, not a countdown — people are treated and get better at every value on the scale. |
| **Clinically** | Successor to MELD-Na (Kim et al., adopted by OPTN 2023). Adds albumin and a female-sex term, and interaction terms between sodium/bilirubin and albumin/creatinine, correcting the under-prioritisation of women under MELD-Na. Driven hardest by creatinine (11.14) and INR (9.09), so hepatorenal physiology and coagulopathy dominate. **Confounded by:** anticoagulation and factor replacement (FFP, PCC) which move INR independent of hepatic synthesis; haemolysis or sepsis-driven cholestasis inflating bilirubin without synthetic decline; albumin infusion — extremely common in this population — which invalidates the albumin term for hours to days; RRT, which is why the creatinine substitution rule exists. **Informs:** transplant listing and priority, and serial trajectory as the practical severity signal in acute liver failure. Note MELD is validated on chronic disease; in ALF it is a severity index, not a listing criterion in itself. |
| **Source** | **Kim et al., *Gastroenterology* 2021** — the derivation paper, and the authority for every coefficient above · [MDCalc](https://www.mdcalc.com/calc/78/meld-score-model-end-stage-liver-disease-12-older) · [UW Hepatitis B Online](https://www.hepatitisb.uw.edu/page/clinical-calculators/meld) |
| **Data note** | `Na` and `Cr` must come from `sodium` / `creatinine` — the **serum** analytes. `abg_sodium` is a different specimen on a different instrument and must never be substituted (`docs/SCHEMA.md`). |

**Worked example — synthetic day 1.** bili 14.6, INR 3.18, Cr 1.74, Na 130, alb 2.7, male,
no dialysis. No input hits a clamp except none — 14.6 > 1, 3.18 > 1, 1.74 ∈ [1,3],
130 ∈ [125,137], 2.7 ∈ [1.5,3.5]. Logs: `ln(14.6) = 2.681022`, `ln(3.18) = 1.156881`,
`ln(1.74) = 0.553885`.

| Term | Arithmetic | Value |
|---|---|---|
| `1.33·female` | `1.33 × 0` | `0.0000` |
| `4.56·ln(bili)` | `4.56 × 2.681022` | `12.2255` |
| `0.82·(137 − Na)` | `0.82 × 7` | `5.7400` |
| `−0.24·(137 − Na)·ln(bili)` | `−0.24 × 7 × 2.681022` | `−4.5041` |
| `9.09·ln(INR)` | `9.09 × 1.156881` | `10.5161` |
| `11.14·ln(Cr)` | `11.14 × 0.553885` | `6.1703` |
| `2.06·(3.5 − alb)` | `2.06 × 0.8` | `1.4800` |
| `−1.83·(3.5 − alb)·ln(Cr)` | `−1.83 × 0.8 × 0.553885` | `−0.8109` |
| `+6` | | `6.0000` |
| **sum** | | **`36.8168`** |

**→ MELD 3.0 = 37.** Day 8 (bili 18.0, INR 2.41, Cr 2.58, Na 136, alb 2.7) works out to
`37.9530` → **38**; the full synthetic series is `37 37 32 33 32 33 34 38`.

**Worked example — check the −1.83 yourself.** The synthetic case's own albumin (2.7)
makes the interaction term small, so the wrong coefficient would not have changed any of
its eight scores. That is the point of A.0: the error hides. To see it bite you need the
term at full size — albumin at its 1.5 floor and creatinine at its 3.0 cap. Take a
male patient with bilirubin 4.0, INR 1.5, creatinine 3.0, sodium 132, albumin 1.5. Logs:
`ln(4.0) = 1.386294`, `ln(1.5) = 0.405465`, `ln(3.0) = 1.098612`.

| Term | Value |
|---|---|
| `4.56 × 1.386294` | `6.3215` |
| `0.82 × 5` | `4.1000` |
| `−0.24 × 5 × 1.386294` | `−1.6636` |
| `9.09 × 0.405465` | `3.6857` |
| `11.14 × 1.098612` | `12.2385` |
| `2.06 × 2.0` | `3.7000` |
| **`−1.83 × 2.0 × 1.098612`** | **`−4.0209`** |
| `+6` | `6.0000` |
| **sum** | **`30.3612` → MELD 3.0 = 30** |

Swap the interaction coefficient for −1.72 and only one row changes:
`−1.72 × 2.0 × 1.098612 = −3.7792`, a difference of `0.2417`. New sum `30.6029`, which
rounds to **31**. Same patient, one point of allocation priority, from one transposed
digit — and nothing on the page would look wrong.

### A.2 MELD-Na (OPTN 2016)

| | |
|---|---|
| **Equation** | `MELD(i) = 10·(0.957·ln(Cr) + 0.378·ln(bili) + 1.120·ln(INR) + 0.643)`, **then rounded to one decimal**<br>then, **only if `MELD(i) > 11`**:<br>`MELD-Na = MELD(i) + 1.32·(137 − Na) − 0.033·MELD(i)·(137 − Na)`<br>otherwise `MELD-Na = MELD(i)` |
| **Units** | `Cr` serum creatinine mg/dL · `bili` total bilirubin mg/dL · `INR` unitless · `Na` serum sodium mmol/L |
| **Bounds** | bilirubin, INR, creatinine floored at 1.0 · creatinine capped at **4.0** (not 3.0 — this differs from MELD 3.0) · dialysis in the prior week sets creatinine to 4.0 · sodium clamped to 125–137 |
| **The one-decimal rounding is load-bearing** | `MELD(i)` is rounded to one decimal **before** the sodium correction, and it then appears **twice** inside that correction, so rounding late shifts the answer. Written as the multiply-then-round form above because the expanded `9.57·ln(Cr) + 3.78·ln(bili) + 11.20·ln(INR) + 6.43` — algebraically identical — invites you to skip the rounding step. `scores.py` does it in this order. *Honest note: across all eight synthetic days the rounding never changes the final integer. It is kept because the policy defines MELD(i) as the rounded value, not because this dataset proves it matters.* |
| **Output** | rounded to nearest integer, then clamped to **6–40** |
| **Plain words** | The older version of the same severity number, kept alongside MELD 3.0 so the two can be compared and so anyone who knows the old scale still recognises the value. Same idea: higher means the liver is in more trouble. |
| **Clinically** | Retained for continuity — most published outcome data and most clinicians' intuition are calibrated on MELD-Na, not MELD 3.0. The sodium correction only applies above MELD 11 because hyponatraemia carries no independent risk at low MELD. Same confounders as A.1 minus albumin. **Informs:** comparison against historical cohorts and against a clinician's remembered thresholds; MELD 3.0 is the operative score. |
| **Source** | [MDCalc](https://www.mdcalc.com/calc/78/meld-score-model-end-stage-liver-disease-12-older) · [UW Hepatitis B Online](https://www.hepatitisb.uw.edu/page/clinical-calculators/meld) |

**Worked example — synthetic day 1.** Cr 1.74, bili 14.6, INR 3.18, Na 130.

| Step | Arithmetic | Value |
|---|---|---|
| `0.957·ln(Cr)` | `0.957 × 0.553885` | `0.530068` |
| `0.378·ln(bili)` | `0.378 × 2.681022` | `1.013426` |
| `1.120·ln(INR)` | `1.120 × 1.156881` | `1.295707` |
| `+ 0.643` | | `0.643000` |
| inner sum | | `3.482201` |
| `× 10`, **round to 1 dp** | `34.82201` → | **`MELD(i) = 34.8`** |
| `MELD(i) > 11`? | yes → apply the sodium term | |
| `+ 1.32·(137 − 130)` | `1.32 × 7` | `+9.2400` |
| `− 0.033·34.8·7` | | `−8.0388` |
| total | `34.8 + 9.24 − 8.0388` | `36.0012` |

**→ MELD-Na = 36.** Day 8 gives `MELD(i) = 36.3` and a total of `36.4221` → **36**. Full
synthetic series: `36 36 32 31 30 31 32 36`.

Compare the two scores on day 1: MELD 3.0 = 37, MELD-Na = 36. The gap is the albumin of
2.7 that MELD-Na cannot see.

### A.3 Child-Pugh — **incomplete from lab data alone**

| | |
|---|---|
| **Equation** | Sum of five items, 1–3 points each; total 5–15. |
| **Items** | total bilirubin mg/dL: `<2` → 1, `2–3` → 2, `>3` → 3 · albumin g/dL: `>3.5` → 1, `2.8–3.5` → 2, `<2.8` → 3 · INR: `<1.7` → 1, `1.7–2.3` → 2, `>2.3` → 3 · **ascites**: none → 1, mild/diuretic-responsive → 2, moderate–severe/refractory → 3 · **hepatic encephalopathy**: none → 1, grade I–II → 2, grade III–IV → 3 |
| **Classes** | A = 5–6, B = 7–9, C = 10–15 |
| **MISSING INPUTS** | **`ascites_grade` and `encephalopathy_grade` are bedside findings — an examination and a clinician's judgement. They are not printed anywhere in a laboratory report and cannot be derived from one.** The dashboard therefore renders Child-Pugh as `complete: false` and names both. See `docs/DECISIONS.md` D9. |
| **Why we do not default them** | Scoring "no ascites, no encephalopathy" because the field is blank silently converts an unknown into a reassuring finding, and would return a low Child-Pugh class for a patient whose ammonia is markedly raised. A wrong low score is worse than no score. |
| **Plain words** | An older, simpler grade of liver damage — A, B or C, where C is worst. It needs two things a blood test cannot see: whether fluid has collected in the belly, and whether the patient is confused or drowsy from the liver. A doctor at the bedside has to supply those. Until someone does, this box stays deliberately blank rather than guessing. |
| **Clinically** | Two of five items are subjective and inter-observer variability is well documented; that is precisely why MELD replaced it for allocation. Retained because it remains the shared vocabulary for surgical risk and for many drug-dosing and procedural decisions. Enter the two grades at the bedside and the score completes immediately. **Confounded by:** albumin infusion, diuretic responsiveness reclassifying ascites, sedation masking or mimicking HE grade in a ventilated patient. |
| **Source variant warning** | Some published versions band INR as `<1.7 / 1.7–2.2 / >2.2`, and older versions use prothrombin time prolongation in seconds (`<4 / 4–6 / >6`) instead of INR. Confirm which variant against [MDCalc](https://www.mdcalc.com/calc/340/child-pugh-score-chronic-liver-disease) before display, and state the variant in the UI. |

**Worked partial — synthetic day 8.** bilirubin 18.0 → `>3` → 3 · albumin 2.7 → `<2.8` → 3
· INR 2.41 → `>2.3` → 3. Lab subtotal **9 of a possible 9**, plus 2–6 unknown points.

A caveat worth stating rather than hiding: in *this* synthetic case the three lab items are
maxed on every one of the eight days, so the total lands in 11–15 whatever the two bedside
grades turn out to be — class **C** regardless. That is a property of these particular
values, not a licence to default the missing items. Change bilirubin to 2.5 and albumin to
3.0 and the same blanks span class A to class C.

### A.4 AARC (APASL ACLF Research Consortium) score — **incomplete from lab data alone**

| | |
|---|---|
| **Equation** | Sum of five items, 1–3 points each; total 5–15. |
| **Items (verify every cut-point — lowest-confidence block in this file)** | total bilirubin mg/dL: `<15` → 1, `15–25` → 2, `>25` → 3 · **HE grade**: none → 1, I–II → 2, III–IV → 3 · INR: `<1.8` → 1, `1.8–2.5` → 2, `>2.5` → 3 · lactate mmol/L: `<1.5` → 1, `1.5–2.5` → 2, `>2.5` → 3 · creatinine mg/dL: `<0.7` → 1, `0.7–1.5` → 2, `>1.5` → 3 |
| **Grades** | I = 5–7, II = 8–10, III = 11–15 |
| **MISSING INPUT** | **`encephalopathy_grade`** — bedside, as in A.3. Renders `complete: false`. |
| **Contested input — lactate** | The only lactate this dataset has is a **blood-gas** lactate: `Lac` is printed on the ABG pages and `config.ANALYTES` carries it as `lactate` in the `abg` group. AARC was derived on a serum/arterial lactate assay. Two honest options, and the scoring module must pick one **explicitly and label it in the UI**: (a) use the ABG lactate and mark the score "computed with blood-gas lactate", or (b) treat it as missing. `scores.py` takes (a) and attaches `LACTATE_NOTE` to every AARC result, complete or not. Do not silently use it as if it were the serum assay. |
| **Plain words** | A severity grade designed specifically for sudden liver failure, from 5 (least severe) to 15. Like Child-Pugh it needs the bedside assessment of whether the patient is confused or drowsy, so it cannot be finished from blood tests alone. |
| **Clinically** | APASL ACLF consensus score; unlike MELD it includes lactate, which captures tissue hypoperfusion and the failing liver's clearance — relevant where sepsis is concurrent. Grade III at presentation and, more importantly, failure of the score to fall by day 4–7 identifies the group in whom transplant assessment should not wait. **Confounded by:** any cause of type-A/type-B hyperlactataemia unrelated to the liver (shock, adrenaline infusion, seizures, metformin), which in a septic patient is the norm rather than the exception; sedation confounding HE grading. **Informs:** timing of transplant referral and of futility discussions. |
| **Source** | [Hep Int (Sarin et al., APASL consensus)](https://link.springer.com/article/10.1007/s12072-017-9816-z) · cut-points cross-check [PMC8579631](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8579631/) |

**Worked partial — synthetic day 8**, and this one shows why the blank matters:

| Item | Value | Band | Points |
|---|---|---|---|
| bilirubin | 18.0 | `15–25` | 2 |
| creatinine | 2.58 | `>1.5` | 3 |
| INR | 2.41 | `1.8–2.5` | 2 |
| lactate (blood gas) | 1.5 | `1.5–2.5` | 2 |
| HE grade | **not recorded** | — | **1, 2 or 3** |
| | | **total** | **10, 11 or 12** |

Default the blank to "none" and the score reads **10 → grade II**. The truth could be
**12 → grade III**, which is the grade that changes whether transplant assessment waits.
One assumed zero, one grade boundary. This is D9 in a single table.

### A.5 Neutrophil-to-lymphocyte ratio (NLR)

| | |
|---|---|
| **Equation** | `NLR = ANC / ALC` (cells/cumm ÷ cells/cumm) — equivalently `neutrophils% / lymphocytes%`, since the total leucocyte count cancels |
| **Units** | unitless. Either both absolute counts or both percentages — **never one of each**. |
| **Availability** | fully computable from the CBC differential. No missing inputs. |
| **Plain words** | Two kinds of white blood cell fight different things: one mostly bacteria, one mostly viruses. Under severe stress the body floods the blood with the first kind and the second kind dies off, so the ratio between them climbs. A ratio that keeps climbing day after day means the body is losing ground; one that falls means it is regaining it. |
| **Clinically** | Composite of stress-driven neutrophilia and steroid/cortisol-mediated lymphopenia — a cheap surrogate for systemic inflammation and immune exhaustion, and prognostic in liver failure and ACLF. **Confounded by:** exogenous corticosteroids, G-CSF, adrenaline, recent surgery, and any lymphopenic state; a very low ALC makes the ratio numerically unstable, so report the ANC and ALC alongside it, never the ratio alone. `scores.nlr()` returns `complete: false` when ALC is zero rather than returning infinity — a zero lymphocyte count is a real and grave result, but it makes the ratio undefined. **Informs:** trajectory reading rather than a single-value decision. |
| **Source** | [PubMed 36571711](https://pubmed.ncbi.nlm.nih.gov/36571711/) — cite for prognostic use only, not for a cut-off |
| **Data note** | The report prints `NLR` directly (`config.ANALYTES["nlr"]`). Our computed value is an **arithmetic gate** against the printed one, not a replacement for it — see `docs/VALIDATION.md`. |

**Worked example — synthetic day 7.** ANC 17114, ALC 993 → `17114 / 993 = 17.2347`. The
page prints `17.2`. Relative difference `0.0020`, comfortably inside
`config.REL_TOLERANCE = 0.06` — gate passes. Cross-check by percentages:
`89.6 / 5.2 = 17.2308`, the same number by a different route. Day 1 was
`9251 / 1322 = 6.998`, printed `7.0`: the ratio has **more than doubled** across the week.

### A.6 Anion gap

| | |
|---|---|
| **Equation** | `AG = Na⁺ − (Cl⁻ + HCO₃⁻)` — the form used here.<br>Variant including potassium: `AG = (Na⁺ + K⁺) − (Cl⁻ + HCO₃⁻)`. |
| **Units** | all four in mmol/L (= mEq/L for these monovalent ions); result mmol/L |
| **Typical range** | 8–12 mmol/L without K⁺; 12–16 with K⁺. Modern ion-selective analysers often run lower, ~3–11. State which form the dashboard used. |
| **Specimen rule — load-bearing** | Bicarbonate exists in this dataset **only** as `abg_hco3`. The gap must therefore be computed entirely within the blood-gas specimen (`abg_sodium`, `abg_chloride`, `abg_hco3`) or not at all. Mixing serum Na⁺/Cl⁻ with an ABG HCO₃⁻ produces a gap made of two different instruments' calibration offsets, which is a manufactured number. `config.ANION_GAP_RANGE = (2.0, 26.0)` is an **extraction-error envelope**, not a clinical range. |
| **Plain words** | A quick arithmetic check on whether acid is building up in the blood, and roughly what kind. The body's salts should balance; when they do not, something acidic is accumulating — often lactic acid from tissues that are not getting enough oxygen. |
| **Clinically** | Separates high-anion-gap metabolic acidosis (lactate, ketones, uraemia, toxins) from normal-gap/hyperchloraemic acidosis (GI or renal bicarbonate loss, large-volume saline). In acute liver failure with sepsis a raised gap is usually lactate, and should be read next to the measured lactate, not instead of it. **Confounded by:** hypoalbuminaemia — every 1 g/dL fall in albumin lowers the measured gap by roughly 2.5 mmol/L, so a "normal" gap in a hypoalbuminaemic patient may conceal a substantial one. Albumin correction should be offered wherever this is displayed. **Informs:** the differential for an acidosis, and whether the lactate is explained. |
| **Source** | [MDCalc](https://www.mdcalc.com/calc/1669/anion-gap) |

**Worked example — synthetic days 1 and 8**, all three terms from the blood gas:

| Day | Na⁺ | Cl⁻ | HCO₃⁻ | `AG` | albumin-corrected `AG + 2.5·(4.0 − alb)` |
|---|---|---|---|---|---|
| 1 | 131 | 99 | 24.1 | `131 − 123.1 = 7.9` | `7.9 + 2.5 × 1.3 = 11.2` |
| 8 | 137 | 105 | 21.8 | `137 − 126.8 = 10.2` | `10.2 + 2.5 × 1.3 = 13.5` |

Uncorrected, both look unremarkable and the day-1 value looks *low*. Corrected for an
albumin of 2.7, day 8 sits above the conventional 12 and the widening across the week is
visible. This is why the correction is not optional in a hypoalbuminaemic patient.

### A.7 Maddrey discriminant function (DF)

| | |
|---|---|
| **Equation** | `DF = 4.6 · (PT_patient − PT_control) + bilirubin_total` |
| **Units** | `PT` seconds (both) · `bilirubin_total` mg/dL · result unitless |
| **Control PT** | the laboratory's own mean normal prothrombin time — `config.ANALYTES["pt_mnpt"]`, printed on the coagulation page. Using a textbook 12 s when the lab prints its own value would be an avoidable error; using another lab's control is meaningless because PT reagents differ. |
| **Threshold** | **DF ≥ 32 defines severe alcoholic hepatitis** — the cut-point at which corticosteroids are considered — in the population the score was derived in. Verified against [MDCalc](https://www.mdcalc.com/calc/40/maddreys-discriminant-function-alcoholic-hepatitis) and recorded in `docs/RESEARCH.md`. It is a threshold **for that aetiology**; see the caveat below before applying it elsewhere. |
| **Availability** | computable — PT, MNPT and bilirubin are all present. |
| **Plain words** | A number that combines how slowly the blood clots with how much yellow pigment has built up. It was designed for one specific kind of liver injury — the alcohol-related kind — to decide whether steroid treatment is worth the risk. Above 32 means severe. |
| **Clinically** | **Derived and validated in alcohol-associated hepatitis to select patients for corticosteroids.** Applying it to acute liver failure of another cause is off-label: it will compute, and it will be high, because both of its inputs are high in any severe hepatic injury — that is not the same as it meaning what it means in alcoholic hepatitis. Display it with the aetiology caveat attached, or suppress it until the aetiology is known. **Confounded by:** anticoagulation and factor replacement (PT), haemolysis and sepsis-associated cholestasis (bilirubin), and reagent-dependent PT variation between labs. **Informs:** steroid candidacy in alcohol-associated hepatitis only. Modern practice largely uses Lille and MELD alongside or instead. |
| **Source** | [MDCalc](https://www.mdcalc.com/calc/40/maddreys-discriminant-function-alcoholic-hepatitis) |

**Worked example — synthetic day 1.** `4.6 × (38.2 − 12.0) + 14.6 = 4.6 × 26.2 + 14.6
= 120.52 + 14.6 = 135.1`. Day 7 (PT 28.9, bili 18.0): `4.6 × 16.9 + 18.0 = 77.74 + 18.0
= 95.7`.

Both are four to five times the "severe" cut-point, which is exactly the caveat above in
numbers: the score saturates. A DF of 135 and a DF of 96 both read "severe", so the
threshold carries no information here and the trend carries all of it. In a case with no
established alcohol aetiology, the honest display is the number with the caveat, or no
number at all.

### A.8 Derived identities

These are **definitions**, not clinical models: the analyser computes each printed value
from the other printed values on the same page. They need no citation and they hold no
matter how ill the patient is — which is exactly why `docs/VALIDATION.md` builds its
strongest gate on them.

| Identity | Units in → out | Synthetic day 1 check | Plain words | Clinically |
|---|---|---|---|---|
| `MCV = PCV / RBC × 10` | % ÷ 10⁶/µL → fL | `34.1 / 3.42 × 10 = 99.71`, page says `99.7` | Average size of a red blood cell, worked out from how much space the cells take up and how many there are. | Analyser-derived, not measured. A disagreement between printed and computed MCV is an extraction error, never biology. Red-cell agglutination is the one real exception and it moves MCHC too. |
| `MCH = Hb / RBC × 10` | g/dL ÷ 10⁶/µL → pg | `11.8 / 3.42 × 10 = 34.50`, page says `34.5` | How much oxygen-carrying pigment sits in an average red cell. | Definitional. Tracks with MCV in most anaemias; discordance implicates a measurement fault first. |
| `MCHC = Hb / PCV × 100` | g/dL ÷ % → g/dL | `11.8 / 34.1 × 100 = 34.60`, page says `34.6` | How concentrated the pigment is inside the cells. | Definitional, and the CBC's own internal quality check. A genuinely high MCHC (>36) means spherocytosis, cold agglutinins, lipaemia or a sampling artefact — investigate the specimen before the patient. |
| `absolute count = TLC × diff% / 100` (× 1000 **if** TLC is in 10³/mm³) | must be the same scale on both sides | `11800 × 78.4 / 100 = 9251.2`, page says ANC `9251` | The actual number of each white-cell type, rather than its share of the total. | **The scale factor is the trap, not the algebra.** `config.ANALYTES["wbc"]` carries `cells/cumm`, matching the absolute counts, so no factor is needed. If a parser substitutes the *canonical* unit `10^3/mm^3` for a value that is actually in cells/cumm, the reported WBC is overstated **1000×** — and both the arithmetic gate and the envelope gate pass, because the stored number never changed, only its label. Make unit substitution scale-aware against the analyte's own `lo`/`hi` envelope. |
| `INR = (PT / MNPT)^ISI` | s ÷ s → unitless | `38.2 / 12.0 = 3.183`, page says `3.18` | Clotting time turned into a ratio, so results can be compared between hospitals. | `config.INR_ISI = 1.0` is an **assumption** — the true ISI is a property of the thromboplastin reagent lot and is not printed on the report. With ISI = 1 the identity reduces to a plain ratio, which is why the gate tolerance is 6% and not tighter. If the reagent ISI is ever obtained, put it in `config` and the gate sharpens. |
| `bilirubin_total = bilirubin_direct + bilirubin_indirect` | all mg/dL | `8.1 + 6.5 = 14.6`, page says `14.6` | The two forms of the yellow pigment add up to the total. | Indirect is normally reported as `total − direct`, so this is a tautology at the analyser and a hard identity for us. A predominantly direct (conjugated) rise points to hepatocellular or cholestatic disease rather than haemolysis. |
| `protein_total = albumin + globulin` | all g/dL | `2.7 + 3.9 = 6.6`, page says `6.6` | The liver's protein plus the immune system's protein equals all the protein in blood. | Globulin is reported as `total − albumin`; again a definitional identity. Rounding to one decimal at the analyser is why the tolerance is relative, not exact. |
| `A:G ratio = albumin / globulin` | g/dL ÷ g/dL → unitless | `2.7 / 3.9 = 0.6923`, page says `0.69` | Compares the two, which shows whether the liver's own protein has fallen further than the rest. | Falls with declining synthetic function or a rising polyclonal globulin. Same rounding caveat. |
| `NLR = ANC / ALC` | cells/cumm ÷ cells/cumm | see A.5 | Two white-cell types divided by each other. | The printed NLR is an independent transcription of two other printed numbers — free redundancy. |
| differential sums to ~100 | % | `78.4 + 11.2 + 9.1 + 1.0 + 0.3 = 100.0` | The five white-cell shares must add up. | `config.DIFFERENTIAL_SUM_RANGE = (97.0, 103.0)`; the report itself states the count is made from several thousand cells and may land between 99 and 101, so the bound is the lab's own, widened for rounding. |

---

## B — Analyte reference

**The reference range printed on the page is the authoritative one** and lives in each
observation's `reference` field (`docs/SCHEMA.md`). The ranges below are the ones the
synthetic report prints (`tools/make_synthetic.py` `REFERENCE`), which is what the
dashboard actually flags against in the demo. A real report will print its own, and they
will differ.

"What it is" is the layman line from `config.ANALYTES[...]["plain"]`, expanded. The
synthetic patient is male (`config.PATIENT_SEX`), which MELD 3.0 needs.

### B.1 Liver function (`liver`)

| Analyte | Unit | Printed range | What it is | High suggests | Low suggests |
|---|---|---|---|---|---|
| Total bilirubin | mg/dL | 0.3–1.2 | The pigment the liver clears from blood; it is what turns skin and eyes yellow when it builds up. | Yellowing, dark urine, itching — the liver cannot clear it. *Clinically:* hepatocellular failure, cholestasis or haemolysis; a MELD driver, and the rate of rise matters more than the level. | Not clinically meaningful. *Clinically:* no low-end pathology. |
| Direct bilirubin | mg/dL | < 0.2 | The part the liver has already processed but cannot get rid of. | The blockage is at or after the liver, not before it. *Clinically:* conjugated hyperbilirubinaemia — hepatocellular injury or obstruction. Direct/total > 0.5 argues against haemolysis. | Nothing on its own. |
| Indirect bilirubin | mg/dL | *(none printed)* | The part the liver has not processed yet. | Red cells are breaking down faster than the liver can keep up, or processing has stalled. *Clinically:* haemolysis, resorbing haematoma, Gilbert's, or overwhelmed conjugation. | Nothing on its own. |
| AST (SGOT) | U/L | < 50 | An enzyme that leaks out when liver cells are damaged. | Active cell damage right now. *Clinically:* also released by muscle, heart and red cells — not liver-specific. AST:ALT > 2 suggests alcohol; values in the thousands suggest ischaemic or toxic injury. A **fall** alongside a rising bilirubin and INR is ominous, not reassuring: it can mean too few cells left to leak. | Not meaningful. |
| ALT (SGPT) | U/L | < 45 | Like AST, leaks from damaged liver cells; more specific to the liver. | Active liver-cell injury. *Clinically:* the more hepatospecific transaminase; peak height correlates with insult type, not with outcome. | Not meaningful. |
| Alkaline phosphatase | U/L | 43–115 | Rises when bile cannot flow out of the liver. | The bile drainage is obstructed or inflamed. *Clinically:* cholestasis; also bone origin — confirm with GGT. Often only modestly raised in acute liver failure. | Rarely relevant (zinc deficiency, hypophosphatasia). |
| Total protein | g/dL | 6.4–8.3 | All the protein in blood; the liver makes most of it. | Usually dehydration or a rise in immune proteins. *Clinically:* interpret only with the albumin/globulin split. | Poor synthesis, malnutrition, or loss via gut or kidney. |
| Albumin | g/dL | 3.5–5.2 | The main protein the liver makes. When it falls, fluid leaks into the belly and legs. | Usually just concentrated blood. *Clinically:* haemoconcentration; no pathological high. | Swelling, fluid in the abdomen, poor healing. *Clinically:* falling synthetic function, but also a negative acute-phase reactant in sepsis and diluted by resuscitation fluid — it is **not** a clean synthesis marker in critical illness. Frequently infused, which invalidates MELD 3.0's albumin term for a period. |
| Globulin | g/dL | 2.3–3.5 | The other main blood protein, made mostly by the immune system. | Chronic inflammation or infection. *Clinically:* polyclonal rise in chronic liver disease and sepsis; a monoclonal rise is a different problem entirely. | Immune deficiency or protein loss. |
| A:G ratio | — | 0.9–2 | Albumin divided by globulin; falls as the liver declines. | Rarely significant. | The liver's own protein has fallen relative to the rest. *Clinically:* a derived value — read the two components, not the ratio. |
| Ammonia | µmol/L | 0–54 | A waste product the liver normally removes. When it builds up it affects the brain, causing confusion and drowsiness. | Confusion, drowsiness, disorientation; at very high levels, brain swelling. *Clinically:* arterial ammonia correlates with HE severity and, above roughly 150–200 µmol/L in ALF, with cerebral oedema and intracranial hypertension. **Heavily preanalytically confounded** — tourniquet time, delay to the ice bath, a fist clenched during draw, and haemolysis all raise it falsely. A single high value with no clinical change deserves a repeat before it drives a decision. Does not correlate tightly enough with HE grade to substitute for the bedside assessment Child-Pugh and AARC need. | Not meaningful. |

### B.2 Clotting (`coagulation`)

| Analyte | Unit | Printed range | What it is | High suggests | Low suggests |
|---|---|---|---|---|---|
| Prothrombin time | s | 10.8–13.2 | How long blood takes to clot. The liver makes the clotting factors, so this lengthens as the liver fails. | Blood is clotting slowly; bruising and bleeding risk. *Clinically:* extrinsic-pathway factor deficiency — factor VII has the shortest half-life, so PT is the earliest and most sensitive synthetic marker in ALF. Also prolonged by vitamin K deficiency and warfarin, which are correctable and must be excluded before attributing it to the liver. | Rarely meaningful; consider a sampling or reagent fault. |
| Mean normal PT | s | *(none printed; the lab constant, 12.0 in the synthetic case)* | The laboratory's own normal clotting time, used as the yardstick. | n/a — it is a constant, not a patient value. *Clinically:* the denominator for INR and the control term in Maddrey DF. If it moves between days, suspect an extraction error or a reagent lot change, not a patient change. | Same. |
| INR | — | "Normal <1.3" | Clotting time as a ratio, so labs can be compared. Above 1.5 means impaired clotting. | Impaired clotting. *Clinically:* ≥1.5 with any encephalopathy defines acute liver failure. A MELD driver. **Does not mean the patient is auto-anticoagulated** — ALF depletes procoagulants and anticoagulants (protein C, S, antithrombin) together, so INR predicts *mortality* well and *bleeding* poorly. Correcting it with plasma to make a number look better destroys the best available trend marker. | Rarely relevant. |
| APTT | s | *(not in the synthetic series; typically 25–35)* | Another clotting-time measure, covering a different part of the clotting cascade. | Broader factor deficiency or an inhibitor. *Clinically:* prolonged with heparin — including line flushes — with DIC, and with advanced synthetic failure. Read next to fibrinogen and platelets. | Usually an acute-phase or sampling effect. |
| Fibrinogen | mg/dL | *(not in the synthetic series; typically 200–400)* | A clotting protein made by the liver; falls when the liver fails or clotting is being consumed. | Acute-phase response. *Clinically:* an inflammatory rise can mask hepatic synthetic failure early. | Bleeding risk. *Clinically:* the discriminator between synthetic failure and DIC when read with platelets, D-dimer and the trend. In sepsis with ALF both mechanisms usually operate. |

### B.3 Kidney and salts (`kidney`) — serum specimen

| Analyte | Unit | Printed range | What it is | High suggests | Low suggests |
|---|---|---|---|---|---|
| Creatinine | mg/dL | 0.67–1.17 | A waste product the kidneys filter out. Rising means the kidneys are struggling, which often follows severe liver disease. | The kidneys are failing too. *Clinically:* the heaviest-weighted MELD 3.0 term. In ALF/ACLF, differentiate hepatorenal syndrome from ATN and from prerenal states — the treatments differ. **Under-estimates** true renal impairment in liver failure: low muscle mass and impaired hepatic creatine synthesis both suppress it, so a "normal" creatinine can accompany a genuinely low GFR. | Low muscle mass or dilution, not good kidney function. |
| Blood urea | mg/dL | 13–43 | Another waste product cleared by the kidneys. | Kidney impairment, dehydration, or bleeding into the gut. *Clinically:* urea:creatinine ratio separates prerenal from renal; **falsely low in liver failure** because urea is synthesised in the liver, so a normal urea does not exclude renal impairment here. | Reduced hepatic synthesis, or overhydration. |
| Sodium (serum) | mmol/L | 136–145 | A salt in blood. It falls in advanced liver disease as the body retains water. | Usually water loss, not salt excess. *Clinically:* free-water deficit; uncommon in this setting. | Low sodium is a bad sign in liver disease. *Clinically:* dilutional hyponatraemia from non-osmotic ADH release; independently prognostic, which is why both MELD variants carry a sodium term. **Correcting it faster than ~8 mmol/L per 24 h risks osmotic demyelination**, a risk amplified in liver disease. |
| Potassium (serum) | mmol/L | 3.5–5.1 | A salt that must stay in a narrow band for the heart to beat normally. | Heart-rhythm danger. *Clinically:* renal failure, acidosis, tissue breakdown, drugs. Confirm a raised value is not haemolysed before acting. | Also a rhythm risk. *Clinically:* diuretics, GI loss, refeeding. Hypokalaemia increases renal ammoniagenesis and can worsen encephalopathy — a correctable HE contributor. |
| Chloride (serum) | mmol/L | 98–107 | A salt that moves with sodium and helps track acid-base balance. | Hyperchloraemic (normal-gap) acidosis, typically from large-volume saline. | Vomiting, gastric losses, or diuretics. |
| Calcium (serum) | mg/dL | 8.6–10.3 | Needed for muscle, nerve and clotting function. | Uncommon here. *Clinically:* investigate separately. | Muscle twitching, rhythm changes. *Clinically:* **must be corrected for albumin** or read as ionised calcium — with a low albumin the total calcium understates the physiologically active fraction. Prefer `abg_calcium` (ionised) when available. |
| Phosphorus | mg/dL | 2.5–4.5 | A mineral that shifts with kidney function and nutrition. | Renal impairment or cell breakdown. *Clinically:* in ALF a **rising** phosphate is a recognised adverse prognostic signal — the regenerating liver consumes phosphate, so failure to fall suggests failure to regenerate. | Refeeding, renal replacement, or brisk hepatic regeneration — the last being the favourable reading. Severe hypophosphataemia impairs respiratory muscle and diaphragm function. |
| Magnesium | mg/dL | 1.7–2.4 | A mineral needed for heart rhythm and nerve function. | Usually renal impairment or supplementation. | Rhythm risk, and makes low potassium impossible to correct until fixed. *Clinically:* common with diuretics, RRT and poor intake; lowers the seizure threshold. |
| Uric acid | mg/dL | *(not in the synthetic series; typically 3.4–7.0)* | A waste product cleared by the kidneys. | Reduced renal clearance or increased cell turnover. *Clinically:* non-specific here; a marker of tissue breakdown and of renal handling. | Rarely relevant; some drugs and, occasionally, advanced hepatic failure. |

### B.4 Blood counts (`blood`)

| Analyte | Unit | Printed range | What it is | High suggests | Low suggests |
|---|---|---|---|---|---|
| Haemoglobin | g/dL | 13.0–17.0 | The oxygen-carrying pigment in red cells. | Dehydration or concentrated blood. | Anaemia or bleeding. *Clinically:* in ALF consider GI bleeding, dilution from resuscitation, haemolysis and marrow suppression. A single value cannot distinguish bleeding from dilution — the trend and the volume given can. |
| RBC count | 10⁶/µL | 4.5–5.5 | How many red blood cells there are. | Concentration or polycythaemia. | Anaemia. *Clinically:* read only with Hb and the indices. |
| PCV / haematocrit | % | 40.0–50.0 | The share of blood made up of red cells. | Haemoconcentration. | Anaemia or dilution. *Clinically:* the most fluid-status-sensitive of the three red-cell measures. |
| MCV | fL | 83.0–101.0 | Average red cell size. | Larger cells than normal. *Clinically:* macrocytosis of liver disease, alcohol, B12/folate deficiency, or reticulocytosis. | Smaller cells. *Clinically:* iron deficiency or chronic disease — points toward occult blood loss. |
| MCH | pg | 27.0–32.0 | Average amount of haemoglobin per red cell. | Tracks MCV upward. | Tracks MCV downward. *Clinically:* iron deficiency. |
| MCHC | g/dL | 31.5–34.5 | Haemoglobin concentration within red cells. | **Check the sample first.** *Clinically:* > 36 is usually spherocytosis, cold agglutinins, lipaemia or an artefact, not a patient finding. | Hypochromia. *Clinically:* iron deficiency. |
| RDW | % | 11.6–14 | How much red cell sizes vary. | A mixed red-cell population. *Clinically:* recent transfusion, recovering or evolving deficiency; a raised RDW is broadly associated with worse outcome in critical illness. | Uniform population; not informative. |
| Total WBC | cells/cumm | 4000–10000 | The infection-fighting cells. High usually means infection; very low is also dangerous. | Infection or inflammation. *Clinically:* in ALF, leucocytosis is also part of the sterile SIRS response, so it is not proof of infection — read with procalcitonin and cultures. | Also dangerous. *Clinically:* overwhelming sepsis, marrow suppression or hypersplenism. A **falling** WBC in an unwell patient is more alarming than a high one. **Unit trap:** this analyte is reported in `cells/cumm`, not `10^3/mm^3`. Substituting the canonical unit label without rescaling the value overstates it 1000× — see A.8. |
| Platelet count | 10³/mm³ | 150–410 | The cells that stop bleeding; they fall in liver disease. | Reactive rise. | Bleeding risk. *Clinically:* multifactorial in ALF — reduced thrombopoietin, splenic sequestration, consumption and sepsis. A steep fall with a falling fibrinogen suggests DIC. |
| MPV | fL | 7.4–10.4 | Average platelet size. | Young platelets being released — consumption or destruction. | Production failure. *Clinically:* supportive, never decisive. |
| Neutrophils % | % | 40–80 | Share of white cells that fight bacteria. | Bacterial infection or stress response. *Clinically:* use the **absolute** count for decisions. | Severe sepsis or marrow failure. |
| Lymphocytes % | % | 20–40 | Share that fights viruses and coordinates immunity. | Viral illness. | Stress, steroids, sepsis. *Clinically:* the denominator of NLR; profound lymphopenia marks sepsis-associated immunosuppression. |
| Monocytes % | % | 2.0–10.0 | Share that clears debris. | Established or resolving infection. *Clinically:* monocyte dysfunction is central to the immune paralysis of ACLF; the percentage alone does not capture it. | Marrow suppression. |
| Eosinophils % | % | 1.0–6.0 | Share linked to allergy and parasites. | Drug reaction (relevant if drug-induced liver injury is on the differential), allergy, parasites. | Expected in acute stress; not informative. |
| Basophils % | % | 0–2.0 | A small white cell population. | Rarely relevant acutely. | Not interpretable. |
| Absolute neutrophils | cells/cumm | 2000–7000 | The actual number of bacteria-fighting cells. | Bacterial infection or stress. *Clinically:* the decision-grade version of the percentage. | **< 500 is neutropenic sepsis risk** and changes management. |
| Absolute lymphocytes | cells/cumm | 1000–3000 | The actual number of virus-fighting cells. | Viral or lymphoproliferative. | *Clinically:* < 1000 marks the immunosuppressed phase of sepsis; NLR denominator. |
| Absolute monocytes | cells/cumm | 200–1000 | The actual number of debris-clearing cells. | Ongoing or resolving infection. | Marrow suppression. |
| Absolute eosinophils | cells/cumm | 20–500 | The actual number of allergy-linked cells. | Drug reaction or parasites. | Expected in acute stress. |
| Absolute basophils | cells/cumm | 20–100 | The actual number of basophils. | Rarely relevant. | Not interpretable. |
| Neutrophil:lymphocyte ratio | — | *(none printed)* | Neutrophils divided by lymphocytes; a rising ratio tracks worsening inflammation. | The body is losing ground against the stress. *Clinically:* see A.5. Report with its two components; unstable at very low ALC. | Recovering balance, or lymphocytosis from another cause. |

### B.5 Infection markers (`infection`)

| Analyte | Unit | Printed range | What it is | High suggests | Low suggests |
|---|---|---|---|---|---|
| Procalcitonin | ng/mL | < 0.5 | Rises specifically with bacterial infection. Above 2 suggests severe systemic infection; above 10 suggests septic shock. | Bacterial infection, and the higher it is the more systemic. *Clinically:* more specific than CRP for bacterial sepsis and its **kinetics** are the usable signal — failure to halve over 48–72 h suggests inadequate source control. **Confounded in liver failure**: PCT is raised by severe hepatic injury, major surgery, burns and renal impairment without infection, so a raised value here is supportive, not diagnostic. Cultures decide. | Bacterial sepsis less likely, but a low PCT does not exclude a localised or fungal infection. |
| CRP | mg/L | < 10 | A general marker of inflammation anywhere in the body. | Inflammation somewhere — not necessarily infection. *Clinically:* **hepatically synthesised, so a failing liver blunts it.** A low CRP in acute liver failure does not exclude sepsis, and this is a common trap. | Low inflammation, or a liver that can no longer mount the response. |
| Interleukin-6 | pg/mL | < 7.0 | An inflammation signal molecule; very high levels accompany severe systemic inflammation. | A very intense inflammatory response. *Clinically:* upstream of CRP and rises earlier; markedly elevated in ACLF and associated with organ failure. Not a standalone treatment trigger. | Lower inflammatory drive. |

### B.6 Blood gas (`abg`) — arterial specimen, bedside analyser

**These are a different specimen measured by a different method with different reference
ranges. They are never substituted for the serum analytes in B.3, and MELD requires the
serum sodium** (`docs/SCHEMA.md`).

| Analyte | Unit | Printed range | What it is | High suggests | Low suggests |
|---|---|---|---|---|---|
| pH (ABG) | — | 7.350–7.450 | How acidic the blood is; it must stay in a very narrow band. | Alkalosis. *Clinically:* respiratory (hyperventilation, common in early HE) or metabolic (vomiting, diuretics). | Acidosis. *Clinically:* in ALF with sepsis, usually lactic. **Arterial pH < 7.3 after resuscitation is a King's College criterion for transplant in paracetamol-related ALF** — read with the aetiology, and confirm the criteria against a current source before displaying them. |
| pCO₂ | mmHg | 35–45 | Carbon dioxide in blood, reflecting breathing. | Under-breathing or fatigue. *Clinically:* hypoventilation, sedation, or exhaustion; a rising pCO₂ in a patient with HE raises intracranial pressure and is an intubation trigger. | Over-breathing. *Clinically:* respiratory compensation for metabolic acidosis, or the hyperventilation of encephalopathy. |
| pO₂ | mmHg | 80–100 | Oxygen dissolved in arterial blood. | Supplemental oxygen. | The lungs are not oxygenating properly. *Clinically:* interpret only against FiO₂; consider ARDS, aspiration, fluid overload, and hepatopulmonary syndrome. |
| Na⁺ (blood gas) | mEq/L | 135–145 | Sodium measured on the bedside machine. | See serum sodium. *Clinically:* direct ISE method — systematically differs from the lab's indirect method, especially with abnormal protein or lipid. **Never feed to MELD.** | Same. |
| K⁺ (blood gas) | mEq/L | 3.500–5.300 | Potassium measured at the bedside. | Rhythm risk; the fast answer while the lab result is pending. | Rhythm risk. *Clinically:* the ABG value is less affected by haemolysis in transit than the serum one. |
| Cl⁻ (blood gas) | mEq/L | 98–106 | Chloride measured at the bedside. | Hyperchloraemic acidosis from saline. | GI or diuretic loss. *Clinically:* the anion-gap chloride — same specimen as the bicarbonate (A.6). |
| Ionised calcium | mg/dL | 4.010–5.290 | The active form of calcium. | Uncommon. | Rhythm and clotting effects. *Clinically:* the **preferred** calcium in a hypoalbuminaemic patient, and falls with citrate accumulation during RRT or massive transfusion — a failing liver cannot clear citrate. |
| Hct (blood gas) | % | 41–51 | Red cell share measured at the bedside. | Haemoconcentration. | Anaemia or dilution. *Clinically:* co-oximetry-derived; use the lab PCV for decisions. **This is the analyte a human reviewer caught being filed as the serum PCV** — same quantity, different specimen, different reference range (`docs/VALIDATION.md`). |
| Glucose (blood gas) | mg/dL | 70–110 | Blood sugar measured at the bedside. | Stress response, steroids, or dextrose infusion. | **A failing liver can let it fall dangerously.** *Clinically:* hypoglycaemia is a hallmark of severe ALF — depleted glycogen and failed gluconeogenesis — and is both a severity marker and an immediately treatable cause of altered consciousness that mimics encephalopathy. Check before attributing drowsiness to HE. |
| Lactate | mmol/L | 0.500–2.200 | Rises when tissues are not getting enough oxygen, or the liver cannot clear it. | Tissue hypoperfusion or failed hepatic clearance. *Clinically:* the liver clears roughly 70% of lactate, so in ALF a raised lactate reflects **both** shock and hepatic failure and cannot separate them. Clearance over 6–24 h is more informative than any single value. Raised by adrenaline, salbutamol, seizures and metformin. An AARC input — see the specimen caveat in A.4. | Normal perfusion and clearance. |
| Total Hb (co-ox) | g/dl | 13.500–18 | Haemoglobin measured by the blood-gas machine. | Haemoconcentration. | Anaemia. *Clinically:* co-oximetry; expect a small systematic offset from the lab Hb. Cross-check, do not merge. |
| O₂Hb | % | 94–97 | Share of haemoglobin carrying oxygen. | Good oxygen loading. | Poor loading, or a dyshaemoglobin displacing oxygen. |
| COHb | % | 1.500–5 | Share bound to carbon monoxide. | CO exposure or smoking. *Clinically:* also modestly raised by haem breakdown in haemolysis. | Normal. |
| MetHb | % | 0.400–1.500 | A form of haemoglobin that cannot carry oxygen. | Oxidising drugs. *Clinically:* causes a saturation gap — pulse oximetry reads falsely reassuring. | Normal. |
| HHb | % | 0–5 | Share not carrying oxygen. | More desaturated haemoglobin. | Well saturated. |
| sO₂ | % | *(none printed)* | Oxygen saturation of the blood. | Well oxygenated. | Hypoxaemia. *Clinically:* co-oximeter-measured, unlike a pulse oximeter's estimate — this one is valid in the presence of dyshaemoglobins. |
| TCO₂ | mmol/L | 23–29 | Total carbon dioxide content. | Metabolic alkalosis or CO₂ retention. | Metabolic acidosis. *Clinically:* moves with bicarbonate; not independently informative. |
| Bicarbonate | mEq/L | *(none printed)* | The blood's acid buffer. Low means acid is building up. | Metabolic alkalosis, or renal compensation for chronic CO₂ retention. | Acid is accumulating. *Clinically:* **calculated from pH and pCO₂, not measured** — it inherits both of their errors. The anion-gap bicarbonate (A.6). |
| Base excess | mmol/L | < 1.000 | How far acid-base balance sits from normal. | Metabolic alkalosis. | Metabolic acidosis, and roughly how much. *Clinically:* a whole-blood-derived summary; a markedly negative base excess in a septic ALF patient usually accompanies the lactate. **The one analyte in this file where the sign is the entire result** — a base excess of −2.7 read as 2.7 inverts the interpretation, and that is a failure only a human reviewer caught (`docs/VALIDATION.md`). |

---

## C — How to read this dashboard

**Read the shape of the line, not the dot.** Eight days of values is a trajectory. One
number on one day is a snapshot with a measurement error attached; four days of rise in the
same direction is a signal. Every chart shows all available days for this reason.

**What each part is for**

| Part | Answers |
|---|---|
| Summary | The five numbers that move the clinical picture in acute liver failure — bilirubin, INR, creatinine, ammonia, platelets (`config.HEADLINE`) — and which way they are going. |
| Flowsheet | The hospital convention: analytes as rows, days as columns, change inline. What a clinician reads without being taught. |
| Scores | MELD 3.0 and MELD-Na computed; Child-Pugh and AARC shown deliberately **incomplete**, naming what a bedside assessment must supply. |
| Glossary | Section B of this file, per analyte. |
| Provenance | For any value: the page it came from, the pixels it was cropped from, the three OCR passes, the four gate verdicts, and who checked it. |

**Arrows mean "getting worse", not "going up".** `config.WORSE_WHEN_RISING` and
`WORSE_WHEN_FALLING` set the direction per analyte, because for bilirubin up is bad and for
albumin down is bad.

**An incomplete score is a feature.** A blank Child-Pugh means a required bedside finding
was never recorded — not that the pipeline failed. Filling that blank with a default would
produce a reassuring number for an unwell patient, which is the single most dangerous thing
this tool could do (`docs/DECISIONS.md` D9). A.4 shows the size of the lie: one assumed
"none" moves AARC from grade III to grade II.

### The limits — read these before drawing any conclusion

| Limit | Consequence |
|---|---|
| **One case, eight days** | Nothing here generalises. There is no cohort, no control and no model fitted to this data. In the demo the case is also **entirely invented**, so it demonstrates the pipeline and nothing about medicine. |
| **Laboratory values only** | No imaging, no ultrasound, no Doppler, no CT. Cirrhosis, portal hypertension, thrombosis and biliary obstruction are invisible to this dataset. |
| **No clinical examination** | No encephalopathy grade, no ascites, no asterixis, no jaundice assessment, no vital signs, no urine output. Two of the four scores are incomplete for exactly this reason. |
| **No medication record** | Albumin infusions, plasma, vitamin K, antibiotics, vasopressors, sedatives, N-acetylcysteine and renal replacement all move the numbers on these charts. Without the drug chart, several confounders named in section B **cannot be excluded**. |
| **No aetiology** | Why the liver failed is not in this dataset, and it determines both prognosis and treatment. It is also why Maddrey DF (A.7) carries a warning. |
| **Every value came from OCR** | There is no digital source text in the PDF (`docs/DECISIONS.md` D1). Four automated gates plus a human check stand behind each number (`docs/VALIDATION.md`), and the provenance crop is one click away — use it when a value looks wrong. The two errors that reached human review, and only human review — a blood-gas haematocrit filed as the serum PCV, and a base excess that lost its minus sign — are both listed in this file's B.6 for that reason. |
| **The interpretive text is rule-based** | Deterministic thresholds and trends, written offline, with no model call on patient data (`docs/DECISIONS.md` D10). It flags patterns. It does not reason about a patient. |

**Therefore: this is not a diagnosis, not a prognosis and not a treatment
recommendation.** It is an organised, audited view of one laboratory dataset, built so that
a treating team can see the trajectory quickly and check any number back to the pixels it
came from. Every clinical decision belongs to the treating team, who have the examination,
the imaging, the drug chart and the patient in front of them.
