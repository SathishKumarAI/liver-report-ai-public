# The data in this repository is invented

Not de-identified. **Invented.** `tools/make_synthetic.py` contains no transformation of any
real measurement — no shifted dates, no jittered values, no scrambled identifiers — so there
is nothing in it to re-identify. That is a stronger guarantee than anonymisation, and it is
the only one worth making for a public repository.

Anonymisation is the weaker claim because a lab series survives the removal of a name. A
rising bilirubin over eight consecutive days, with a matching creatinine and a matching INR,
is as identifying to anyone holding the chart as the name would have been. Shifting the dates
and rounding the values does not fix that; it only makes the record harder to check.

## What is real and what is not

| | Status |
|---|---|
| Every clinical value, date, timestamp, sample identifier | **Invented.** `tools/make_synthetic.py` is the only source |
| The pipeline, the gates, the parser, the scores | Real code, unchanged |
| Pixel measurements — row luminance, band heights, page geometry | Real, measured. They describe a scanner and a page layout, not a person |
| Page counts and OCR agreement counts (112 pages, 471 values, 444 unanimous) | Real. They are the evidence for the engineering claims and identify nobody |
| Failure modes in `docs/OCR-NOTES.md` | Real failures, real fixes, demonstrated on synthetic values |
| The institution, the clinicians, the admission dates, the patient | **Absent by design**, everywhere in this repository |

## The shape of the synthetic case

An eight-day admission for acute-on-chronic liver failure, running **2024-03-04 to
2024-03-11** — a date range chosen to be obviously fictional and well away from anything
real. Documents prefer "day 1 … day 8"; the ISO dates exist because the pipeline's time axis
needs timestamps.

Clinically shaped rather than random, because a dashboard demonstrated on noise shows
nothing about whether it works. The shape is borrowed from published reference ranges and
textbook trajectories: a bilirubin that climbs, a creatinine that turns up late, an INR that
improves then stalls, a white count and NLR that rise as the picture becomes septic, a
lactate that settles. Most analytes are measured on some days and not others, because that is
the realistic case and the one the pipeline has to survive.

**The series is arithmetically self-consistent**, so the validation gates exercise real
logic rather than waving synthetic data through:

| Identity | Day 1 |
|---|---|
| `bilirubin_total = direct + indirect` | `8.1 + 6.5 = 14.6` ✓ |
| `protein_total = albumin + globulin` | `2.7 + 3.9 = 6.6` ✓ |
| `A:G = albumin / globulin` | `2.7 / 3.9 = 0.69` ✓ |
| `MCV = PCV / RBC × 10` | `34.1 / 3.42 × 10 = 99.7` ✓ |
| `MCH = Hb / RBC × 10` | `11.8 / 3.42 × 10 = 34.5` ✓ |
| `INR ≈ PT / MNPT` | `38.2 / 12.0 = 3.18` ✓ |
| `ANC = WBC × neutrophil% / 100` | `11 800 × 78.4 / 100 = 9 251` ✓ |
| `NLR = ANC / ALC` | `9 251 / 1 322 = 7.0` ✓ |
| differential sums to ~100 | `78.4 + 11.2 + 9.1 + 1.0 + 0.3 = 100.0` ✓ |

Scores and patterns are **not** hand-written: `make_synthetic.py` calls `src.scores`,
`src.patterns` and `src.build` directly, so the demo runs the same code path the pipeline
does rather than a parallel fake.

**Synthetic records say so.** Every observation carries `provenance.synthetic: true` and the
dataset carries `"synthetic": true` at the top level. A dataset built from a real document
carries neither. Nothing has to remember which one is loaded.

## Regenerating it

```
python tools/make_synthetic.py              # writes data/labs.json
python tools/make_synthetic.py --out X      # elsewhere
python run.py build                         # dashboard from that dataset
```

Output as of this writing:

```
observations : 308
days         : 2024-03-04 to 2024-03-11
patterns     : 78
MELD-Na      : [36, 36, 32, 31, 30, 31, 32, 36]
```

To change the case, edit `SERIES` at the top of the generator. Two things to keep true:
the identities in the table above (otherwise gate 3 fails on data that is supposed to be
clean), and the printed `REFERENCE` strings (the interpretation flags are derived from them,
not stated).

## Pointing the pipeline at a real document

Everything runs locally. No cloud OCR, no hosted model, no CDN, no web font.

```
python tools/install_hooks.py          # once per clone: installs the pre-commit PHI guard
# put the report at data/raw/<name>.pdf
python run.py                          # render -> OCR -> extract -> build
python run.py check                    # PHI containment + coverage report
python run.py serve                    # dashboard on 127.0.0.1:8080
```

The containment rules, in the order they will bite:

| Rule | Enforced by |
|---|---|
| `data/` and `dist/` must be gitignored | `run.py` refuses to start otherwise. It writes patient data there, and the moment it does so into a tracked directory the leak already exists |
| No patient identifier reaches a commit | The pre-commit hook from `tools/install_hooks.py`, running `tools/scan_phi.py` over staged content |
| The identifier list is itself never committed | It lives in `data/phi_patterns.txt`, gitignored, generated by the pipeline. A scanner that ships the secrets it scans for is not a scanner |
| No value goes on a chart unverified | `build.py`'s export gate (`docs/VALIDATION.md`) |

`scan_phi.py` checks three layers, because each catches what the others miss: direct
identifiers, quasi-identifiers (institution, admission dates, referring clinician — the layer
people forget, and the one that decides whether a "de-identified" repository is actually
anonymous), and value fingerprints — the real measured series, which is the medical record
whatever the name has been changed to.

A first extraction run is roughly 20 minutes (three OCR passes × 112 pages). `run.py build`
is seconds, and analyte mapping is re-derived at build time, so a `config.ANALYTES` fix does
not need a re-extract; a `parse.py` fix does.

**Nothing produced from a real document belongs in this repository** — not a dataset, not a
crop, not a page image, not a screenshot of the dashboard, not a "just one example" value in
a doc or a docstring. The synthetic case exists so that no such example is ever needed.
