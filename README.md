# Liver report

Turns a scanned hospital laboratory PDF into a verified per-analyte time series and an
offline dashboard, with a local chat you can ask questions of. Every charted number is
traceable back to the pixels it was read from.

## Privacy first — read this before anything else

**This repository ships invented data only.** The demo dataset in
`tools/make_synthetic.py` is fabricated, not de-identified: no real measurement was
transformed into it, so there is nothing in it to re-identify. That is a stronger
guarantee than anonymisation and the only one worth making in public.

| | |
|---|---|
| Real documents | Never committed. `data/` and `dist/` are gitignored; `run.py` refuses to start if they are not |
| Network | None. No cloud OCR, no hosted model API, no CDN, no web font, no analytics. The chat talks to a local model server bound to `127.0.0.1` |
| Guard | A pre-commit hook blocks patient file types and identifier patterns in staged content (`python tools/install_hooks.py`) |
| Scanner | `tools/scan_phi.py` — three layers: direct identifiers, quasi-identifiers, value fingerprints — run locally, from the hook, and in CI |
| Denylist | Lives outside the public tree. A scanner that ships the secrets it scans for is not a scanner |

The full design, and the checklist for pointing this at your own documents, is in
[PRIVACY.md](PRIVACY.md). Read it before you copy a real PDF anywhere near this repo.

## Quickstart — the synthetic demo

Needs Python 3.12 and nothing else; no external binary is touched on this path.

```
mkdir dist                         # see the note below
python tools/make_synthetic.py     # invented dataset -> data/labs.json

python -c "import json; from src import build, config as C; C.DIST.mkdir(parents=True, exist_ok=True); C.DASHBOARD.write_text(build.render(json.loads(C.LABS_JSON.read_text(encoding='utf-8')), provisional=False), encoding='utf-8')"

python run.py serve                # dashboard + local chat at http://127.0.0.1:8080/
```

> **Two known rough edges, both tracked in [STATUS.md](STATUS.md) as the next actions.**
> `run.py` tests containment with `git check-ignore data`/`dist` and git will not match the
> `dist/` pattern against a directory that does not exist yet, so on a fresh clone it
> refuses to start until `dist/` exists. And `run.py build` re-derives everything from
> `data/raw_observations.json`, which only an extraction run produces — hence the `python
> -c` line above instead of a command.

Demo dataset: 308 observations across 8 days, MELD-Na `36 36 32 31 30 31 32 36`.

## On a real document

```
python tools/install_hooks.py      # do this FIRST, and verify it blocks a commit
python run.py                      # render -> OCR -> extract -> build
python run.py check                # containment + coverage report
```

Put the PDF at `data/raw/<name>.pdf`. Expect ~20 minutes for a hundred-page document:
three OCR passes per page. `run.py build` afterwards is seconds.

## What it produces

- `data/labs.json` — the dataset, modelled on
  [FHIR R4 Observation](https://hl7.org/fhir/R4/observation.html), with a `provenance`
  block per value: page, bounding box, evidence crop, every OCR reading, which validation
  gates it cleared, whether a human confirmed it.
- `dist/dashboard.html` — one self-contained page, nine tabs, zero network requests.
- `data/verify/sheet_*.png` — contact sheets pairing every value with the pixels it came
  from, grouped by analyte, for human review.

## Where to look

| Question | File |
|---|---|
| Can I trust this with a real document | `PRIVACY.md` |
| Why is anything the way it is | `docs/DECISIONS.md` |
| What OCR breaks on and the measured fix | `docs/OCR-NOTES.md` |
| The dataset shape | `docs/SCHEMA.md` |
| Formulas, coefficients, citations | `docs/CLINICAL.md` |
| How values are validated | `docs/VALIDATION.md` |
| Pointing this at a different report | `docs/PROMPT.md` |
| What already exists in the world | `docs/RESEARCH.md` |
| Where work stopped | `STATUS.md` |

## Change → file

| Change | File |
|---|---|
| An analyte, alias, unit, envelope, plain-English text | `src/config.py` |
| Page rendering, band geometry | `src/render.py` |
| Tesseract passes, band reading | `src/ocr.py` |
| Sample timeline, timestamp repair | `src/samples.py` |
| Column parsing, wrapped names | `src/parse.py` |
| Validation gates | `src/validate.py` |
| Clinical scores and their citations | `src/scores.py` |
| Trend and cluster rules | `src/patterns.py` |
| Dataset assembly, export gate | `src/build.py` |
| Styling, charts, tab markup | `src/dashboard_assets.py` |
| Local retrieval + chat | `src/rag.py` |
| The demo case | `tools/make_synthetic.py` |
| What must never be published | `tools/scan_phi.py`, `.gitignore` |

## Requirements

No pip installs. Python 3.12, standard library only. The pipeline shells out to tools that
have to be on `PATH`:

| Tool | Used for | Needed for the synthetic demo? |
|---|---|---|
| `tesseract` | OCR | no |
| `pdftoppm` (poppler) | PDF → page images | no |
| `magick` (ImageMagick) | crops, row-luminance profiling, contact sheets | no |
| `ollama` *(optional)* | the Ask AI tab; prefers an open-weight medical model | no |

Without Ollama every tab still works; only the chat is unavailable, and it says so.

## What this is not

A data-presentation tool, **not a diagnostic device**. It restates measured laboratory
values, computes published scores from them, and flags trends. It has no imaging, no
examination findings and no medication record — several scores it reports are deliberately
`complete: false` for exactly that reason. Clinical decisions belong to the treating team.
