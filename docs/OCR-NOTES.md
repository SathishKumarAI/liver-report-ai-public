# OCR notes — what breaks on this document, and the measured fix

Everything here was found by measurement, not by reasoning about what ought to work.
Each entry gives the failure, the evidence, and the fix that was verified against the page
images.

> Pixel measurements, band geometry and page counts describe the **scanner and the document
> layout**, and are reported as measured. Every clinical value quoted is from the synthetic
> case (`docs/SYNTHETIC-DATA.md`).

## The source

A 112-page CamScanner PDF of laboratory reports. **No text layer at all** —
`pdftotext -layout` over all 112 pages returns 112 characters, one form feed per page.
One full-page RGB JPEG per page at ~275 dpi. Every number in the dataset therefore comes
from OCR, which is why validation is a larger part of this project than extraction.

---

## 1. The grey sample band vanishes — and takes the time axis with it

**Failure.** A sweep for `Sample No` across the OCR output of all 112 pages matched
**zero times**. That band carries `Collection Date`, the timestamp every observation and
every chart hangs from. The failure is silent: you get plausible values with no clock.

**Cause.** The band is white text on a mid-grey fill. Tesseract assumes dark-on-light and
binarises it away.

**Fix.** Locate the band geometrically, then invert only that strip.

Row-luminance profiling finds it without numpy: `magick <page> -colorspace gray -resize 1x! txt:-`
collapses the image to one column, so each output pixel is the mean of one row. Measured on
page 40 at 300 dpi:

| region | rows | height | mean luminance |
|---|---|---|---|
| column header band | 1926–1997 | 72 | 81 |
| sample metadata band | 2004–2065 | 62 | 127 |
| body text lines | — | 14–27 | 170–191 |

Height and darkness together separate bands from text. **Darkness alone does not** — the
dense italic `Comments:` paragraph reads as a run of dark rows, and the first classifier
paired consecutive text lines into phantom bands.

## 2. Reading the band needs four separate things right

Each was found by a failing attempt:

| Problem | Symptom | Fix |
|---|---|---|
| Crop padded above/below | `--psm 7` returns **empty string** — it sees two lines | Crop tight to the band |
| Band read as one wide strip | Worked on 7 of 55 bands | Read **one field at a time** in its own x-window |
| Digit whitelist on those windows | Returns empty | **No whitelist** — the window contains the field *label* too |
| Window runs to the page edge | Empty | Keep inside the printed band (x 0.04–0.96); margin inverts to a black slab |

No single `--psm` reads every field: the sample number only comes out under `psm 8`, the
report date only under `psm 6`, while `psm 7` reads the collection and acknowledgement
times cleanly and returns nothing for the other two. So combinations are tried in order
until each field parses, preferring a reading that includes a clock time.

Verified against page 40 read by eye: sample `SYN100317`, collected `06/03/24 07:15`,
acknowledged `09:42`, reported `11:08` — all exact.

**Result: 47 of 55 bands read automatically.** The remaining 8 were read by eye from the
band images and recorded in `data/overrides.json`.

## 3. Timestamps that OCR corrupts into *valid* dates

Two bands produced dates that parse perfectly and are wrong:

- page 38: month `03` read as `08` → `2024-08-06`
- page 98: day `11` read as `13` → `2024-03-13`

Neither is catchable by date validation. They are caught by the document as a whole: an
inpatient admission is a **contiguous run of days**. A fixed ±N-day window does not work —
`03-13` sits only three days out and passes any window wide enough to be safe. Contiguity
does work, because the run 04…10 simply does not reach 13.

Repair uses evidence rather than assumption: bands whose sample-number **stem** matches are
aliquots of the same draw and share a collection time, which restored page 38 to page 40's
verified `2024-03-06T07:15`. Page 98 could not be repaired automatically, stayed flagged,
and was read by eye as `11/03/24 00:21` — the last day of the eight-day run.

## 4. Names and units wrap; panels span pages

Page 17 prints the analyte as `ABSOLUTE BASOPHIL` / `COUNT` and its unit as `10^3/mm^` / `3`.
A line-oriented parser sees a value whose name is half missing and pairs it with the wrong
analyte — an error that is well-formed and plausible, which is the worst kind here.

Hence geometry: cluster words into lines by y-overlap, assign columns by x, then rejoin a
TEST-column line that has no RESULT-column word to the row above.

Page 17 also has **no sample band** — it is a CBC continued from page 16. **58 of 112 pages
are continuations.** They inherit the last sample seen; without that rule half the document
contributes values with no timestamp.

## 5. The punch hole eats the first character

`PROTHROMBIN TIME` arrives as `>ROTHROMBIN TIME` and matches no alias exactly. A similarity
fallback (`difflib`, cutoff 0.86) recovers it. The cutoff is deliberately high: mapping a
value onto the *wrong* analyte is far worse than dropping it, because a dropped value shows
up in the coverage count while a mismapped one does not.

## 6. Pass C was silently dead

Three "decorrelated" OCR passes were configured, the third being a whole-page read with
`tessedit_char_whitelist` set to digits. That destroys every analyte name on the page, so
the geometric parser matched no rows and pass C returned `None` for all 471 values. The
ensemble was running on two passes, not three, and the contact sheets showed it
(`BILIRUBIN_TOTAL=18.0/18.0/None` on every row).

The whitelist belongs on the **value box alone**, which contains only a number. Applied
there it does its job — `O`/`0`, `l`/`1`, `S`/`5`, `B`/`8` confusion becomes impossible by
construction. Re-reading every value from its own bounding box: **444 agree, 27 disagree,
0 unreadable.**

**Why it survived so long:** the ensemble gate reported `pass` throughout, because two
agreeing passes and one abstention looks exactly like agreement unless you count the voters.
A gate that cannot fail is not a gate — `None` from a configured pass is now a fault, not an
abstention.

## 7. Every remaining disagreement is a decimal point

All 27 are the same failure — a decimal lost, turning `1.5` into `15.0`. Two resolvers:

- **The printed reference range** (`validate.choose_value`). One candidate is inside it, the
  other an order of magnitude outside. Uses the lab's own printed range, no clinical
  judgement.
- **The analyte's own distribution** (`validate.resolve_decimal_shifts`). Carboxyhaemoglobin
  reads 1.4, 1.6, 1.5 across the document, so `15.0` is not a sick patient, it is a missing
  decimal. It fires only when the chosen value is ≥5× off the analyte's own median **and**
  exactly one alternative OCR reading sits within a factor of 3 of that median. Genuinely
  extreme values — a bilirubin 15× its reference ceiling — are untouched, because the whole
  series is extreme and the median moves with it.

Every correction is recorded in `provenance.decimal_shift_corrected` with the value it
replaced, and the observation is forced back into the review queue. A silent auto-correction
would be indistinguishable from the OCR error it fixed.

## 8. Found only by looking: two errors no gate caught

Both were caught by reading the evidence crops, and neither would have been found by any
automated check in this pipeline.

**Blood-gas Hct filed as serum PCV.** `PCV` and `HCT` were both aliased to `pcv`, so the
blood-gas haematocrit (ref 41–51) was recorded as serum PCV (ref 40.0–50.0) and fed into
the MCV/MCHC identity checks from a different instrument. Every reading was *correct*; the
label was wrong. Fixed by giving `HCT` to `abg_hct` and leaving `pcv` only `PCV`
(`docs/DECISIONS.md` D13).

**Base excess lost its minus sign.** `BE(B) -0.6`, `BEecf -3.1` and `-2` were recorded as
`+0.6`, `+3.1`, `+2`. The value regex had no provision for a leading `-`, and OCR sometimes
separates the sign from its digits. Base excess is *routinely* negative — it is how
metabolic acidosis is reported — so the sign error inverts the clinical meaning in a
patient whose lactate is rising.

Both are the argument for the human gate: three OCR passes agreeing tells you the *glyphs*
were read correctly. It cannot tell you the number was filed under the right analyte, or
that the character the parser never looked for was there.
