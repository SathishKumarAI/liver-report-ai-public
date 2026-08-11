# STATUS — written when work stopped

Read this before touching anything.

## Where it is

The public repository: the pipeline, the documentation, and a wholly invented demo case.
No real document, no derived value, and nothing that came off one has ever been in this
tree — see `PRIVACY.md`.

| | |
|---|---|
| Tests | `python -m pytest tests -q` → **79 passed** in 0.14 s |
| Synthetic demo | `python tools/make_synthetic.py` → 308 observations, 8 days, 78 patterns |
| Demo scores | MELD-Na `36 36 32 31 30 31 32 36`; MELD 3.0 on the days albumin exists |
| Dashboard | renders from the synthetic dataset, ~930 KB, nine tabs, zero external URLs |
| Containment | `.gitignore`, run-time refusal, pre-commit guard, three-layer scanner, CI job |

The engineering write-ups (`docs/OCR-NOTES.md`, `docs/VALIDATION.md`, `docs/DECISIONS.md`,
`docs/CLINICAL.md`, `docs/SCHEMA.md`, `docs/RESEARCH.md`) describe measurements taken while
building the pipeline against a real scanned report. The findings and the method are
reproduced; every clinical value quoted in them is the synthetic one.

## The environment traps, in the order they will bite

1. **`run.py` refuses to run on a fresh clone.** `guard_phi()` calls
   `git check-ignore -q data` / `dist` **without a trailing slash**. Git will not match the
   directory pattern `dist/` against a path that does not exist yet, so it reports
   `dist/ is not gitignored` on any clone where the directory has not been created.
   Verified: `git check-ignore -v dist` → exit 1; `git check-ignore -v dist/` → matches
   `.gitignore:11`. Fix is one edit — pass `"data/"`, `"dist/"`, as `tools/install_hooks.py`
   already does. Workaround until then: `mkdir dist`.
2. **There is no `labs.json` → dashboard command.** `build.main()` always starts from
   `data/raw_observations.json`, which only an extraction run produces, so
   `python run.py build` cannot render the synthetic dataset. `build.render(dataset,
   provisional=False)` does, and that one-liner is in the README. This is the first thing
   to fix; the demo is the repository's front door.
3. **`src/config.py` hardcodes absolute Windows binary paths**, one of them under a
   personal user directory. It will not resolve on any other machine, and a username does
   not belong in a public repo. Needs `shutil.which` with an env-var override.
4. **Subprocess output must be decoded UTF-8.** Windows defaults these pipes to cp1252 and
   tesseract emits UTF-8; one unusual glyph raises `UnicodeDecodeError` from a reader
   thread. Already handled in `ocr.py`/`render.py` — do not remove it.
5. **Files written by PowerShell arrive CRLF.** The pre-commit guard strips `\r` before
   matching, because once it did not and passed a file containing an identifier.
6. **A full extraction is ~20 minutes** (three OCR passes per page); `build` is seconds.
   Analyte mapping is re-derived at build time, so a `config.ANALYTES` fix does **not** need
   a re-extract. A `parse.py` fix does.

## What is deliberately incomplete

- **Child-Pugh and AARC report `complete: false`.** They need ascites grade and hepatic
  encephalopathy grade — bedside findings absent from lab data. The doctor view exposes them
  as inputs. Do not default them: defaulting "no encephalopathy" gives a reassuring score to
  a patient whose ammonia is 79 µmol/L against a ceiling of 54.
- **MELD 3.0 computes on the days serum albumin exists**, which in the synthetic case is
  day 1 only, mirroring the real behaviour: albumin is often measured once. MELD-Na needs no
  albumin and covers all 8 days.
- **Dialysis status is an assumption.** MELD 3.0 assumes no renal replacement therapy and
  states the assumption on the row. If the patient was dialysed the score understates
  substantially.
- **Qualitative results are not modelled.** Cultures, serology, urine and the peripheral
  smear parse as text but never become observations.
- **RAG retrieval ranking is mediocre.** "kidney function" surfaces electrolytes above
  creatinine and urea. Chunking and citations work; the lexical ranking needs
  analyte-key weighting.
- **`tools/check_dashboard.py` does not pass on the synthetic render.** Four of its
  MUST_CONTAIN assertions are Formulas-tab content, and `make_synthetic.py` emits
  `"formulas": []`. Either the generator should populate formulas from `src/scores.py`, or
  the check should scope those assertions to a real extraction. It is an accurate report of
  a gap, not a false alarm.

## The next actions

1. Render path for the synthetic dataset (trap 2) and the `check-ignore` slash (trap 1).
   Between them they are the whole first-run experience.
2. Portable binary resolution (trap 3).
3. Populate `formulas` in the synthetic dataset so `check_dashboard.py` passes, or narrow
   the check.
4. Accessibility and contrast work carried over from the UX audit: a missing lab flag
   currently renders identically to a normal one; `<summary>` hit targets are 23 px against
   the 24 px WCAG 2.2 minimum; screen readers hear "H" rather than "high"; the wide
   flowsheet has no row/column association; several palette tokens fail contrast
   (`--line` at 1.38:1 on cards is the worst).
5. Never word a direction-of-travel finding as reassurance while the value is still an
   order of magnitude outside its range. "Better" on a bilirubin of 18.0 mg/dL is false
   comfort.
6. Model qualitative results, and weight exact analyte-key matches in RAG ranking.

## What was got wrong, so it is not repeated

Recorded in full in `docs/DECISIONS.md`; the two worth carrying:

- **Assuming what the document contains.** A sweep for `LACTATE` found nothing, and it went
  into the docs as unavailable. The blood-gas analyser prints it `Lac`, on 13 pages,
  elevated — and the same assumption hid an entire arterial blood gas panel. Build the
  dictionary from a scan of the document, never from expectations.
- **Trusting agreement over inspection.** Three OCR passes agreed, four gates passed, and
  two real errors survived: a blood-gas haematocrit filed as serum PCV, and a base excess
  recorded without its minus sign. Both were found only by looking at the crops. Agreement
  proves the glyphs were read; it cannot prove the number was filed correctly.
