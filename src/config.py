"""Every constant in the pipeline.

Owns: paths, render/OCR tuning, the analyte dictionary, display grouping, palette.

Does NOT own: any logic. Nothing here reads a file or shells out. If you are
hunting a magic number anywhere else in src/, it is a bug -- it belongs here.

The analyte dictionary is the file you edit when a new test appears in a future
report. Nothing else needs to change.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Paths.  data/ and dist/ are gitignored: they hold PHI.
# --------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
RAW = DATA / "raw"
PAGES = DATA / "pages"
OCR_DIR = DATA / "ocr"
CROPS = DATA / "crops"
DIST = REPO / "dist"

LABS_JSON = DATA / "labs.json"
REVIEW_JSON = DATA / "review.json"
PHI_PATTERNS = DATA / "phi_patterns.txt"
DASHBOARD = DIST / "dashboard.html"

# External binaries. Resolved at import so a missing tool fails loudly and early.
TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MAGICK = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
PDFTOPPM = r"C:\Users\PRANAS\AppData\Local\Programs\MiKTeX\miktex\bin\x64\pdftoppm.exe"

# --------------------------------------------------------------------------
# Render + band detection.
# --------------------------------------------------------------------------
RENDER_DPI = 300          # 150 loses the thin white-on-grey band text
JPEG_QUALITY = 92

# A page row counts as "dark" below this mean luminance (0-255).
DARK_ROW_MAX = 195

# Separating a filled band from a dense line of italic text needs BOTH of these.
# Measured on page 40 at 300 dpi:
#
#   header band   rows 1926-1997  h=72  mean lum  81
#   sample band   rows 2004-2065  h=62  mean lum 127
#   body text     h=14..27              mean lum 170-191
#
# Height alone nearly separates them (72/62 vs <=27) and darkness confirms it.
# Using darkness alone was the first attempt and it misfired: the italic
# "Comments:" paragraph is dense enough to read as a run of dark rows, and the
# classifier paired consecutive text lines into phantom header/sample bands.
BAND_MIN_HEIGHT_FRAC = 0.012      # ~42 px on a 3509 px page
BAND_MAX_HEIGHT_FRAC = 0.035      # ~123 px
BAND_MAX_MEAN_LUM = 160

# The scanner leaves a dark strip at the sheet edge; ignore the top of the page.
BAND_SEARCH_TOP_FRAC = 0.10
# --------------------------------------------------------------------------
# OCR.
# --------------------------------------------------------------------------
# Three deliberately decorrelated passes. See docs/OCR-NOTES.md for why one is
# not enough and why pass C exists.
OCR_PASSES = {
    "A": {"psm": "6", "preprocess": "gray"},
    "B": {"psm": "4", "preprocess": "otsu"},
    "C": {"psm": "6", "preprocess": "gray", "whitelist": "0123456789.<>-+"},
}
# Grey metadata band: invert, upscale, stretch contrast. Proven on p40.
BAND_MAGICK_ARGS = [
    "-colorspace", "gray", "-resize", "300%", "-negate",
    "-normalize", "-level", "20%,80%", "-sharpen", "0x1",
]
BAND_PSM = "7"
MIN_WORD_CONF = 55        # tesseract per-word confidence floor

# --------------------------------------------------------------------------
# Validation tolerances.
#
# Deliberately loose. These gates exist to catch OCR corruption -- a dropped
# decimal point, a digit read as a letter -- not to second-guess the analyser.
# A tight tolerance here would flag rounding and train us to ignore the alarm.
# --------------------------------------------------------------------------
REL_TOLERANCE = 0.06      # 6% on derived-quantity identities
DIFFERENTIAL_SUM_RANGE = (97.0, 103.0)   # report itself states 99-101
INR_ISI = 1.0             # assumed; INR ~= (PT/MNPT)^ISI
ANION_GAP_RANGE = (2.0, 26.0)

# Unit strings this report legitimately prints. Used to tell "the page really
# does disagree with the dictionary" (trust the page, flag it) from "OCR turned
# mmHg into arnitg" (use the dictionary). Compared with punctuation and case
# squashed out.
# Sex is a required MELD 3.0 input and is not derivable from the lab values, so
# it has to live somewhere. It sits here as a configurable default rather than
# inside a scoring call, and carries no other demographic detail: age is not
# used by any calculation in this project and is therefore not stored.
PATIENT_SEX = "male"

KNOWN_UNITS = {
    "mg/dL", "g/dL", "g/dl", "mmol/L", "mEq/L", "umol/L", "ng/mL", "pg/mL",
    "U/L", "IU/L", "%", "mmHg", "fL", "fl", "pg", "Seconds", "cells/cumm",
    "10^3/mm^3", "10^6/uL", "mg/L", "ratio",
}

# --------------------------------------------------------------------------
# The analyte dictionary.
#
#   key      -> canonical id used everywhere downstream
#   display  -> what a human sees
#   aliases  -> strings seen on the page, INCLUDING observed OCR corruptions.
#               Matched case-insensitively after whitespace/punctuation squash.
#   unit     -> expected unit (for sanity, not conversion)
#   lo/hi    -> PHYSIOLOGICAL ENVELOPE, not a reference range. A value outside
#               this is an extraction error, not a sick patient. Kept wide.
#   group    -> dashboard grouping
#   plain    -> one-sentence layman meaning (Glossary tab)
#
# ABG analytes are kept SEPARATE from their serum equivalents on purpose.
# A blood-gas Na+ and a lab serum sodium are different specimens measured by
# different methods with different reference ranges. MELD requires the serum
# value; silently mixing them would corrupt the score.
# --------------------------------------------------------------------------
ANALYTES = {
    # ---- Liver: synthetic function and injury ----
    "bilirubin_total": dict(
        display="Total bilirubin", aliases=["TOTAL BILIRUBIN", "T BILIRUBIN", "TOTAL BILIRUBIN Serum"],
        unit="mg/dL", lo=0.05, hi=60, group="liver",
        plain="The pigment the liver clears from blood. It rises when the liver cannot process it, and is what makes skin and eyes look yellow."),
    "bilirubin_direct": dict(
        display="Direct bilirubin", aliases=["DIRECT BILIRUBIN", "CONJUGATED BILIRUBIN"],
        unit="mg/dL", lo=0.01, hi=50, group="liver",
        plain="The part of bilirubin the liver has already processed but cannot excrete."),
    "bilirubin_indirect": dict(
        display="Indirect bilirubin", aliases=["INDIRECT BILIRUBIN", "UNCONJUGATED BILIRUBIN"],
        unit="mg/dL", lo=0.01, hi=40, group="liver",
        plain="The part of bilirubin the liver has not processed yet."),
    "ast": dict(
        display="AST (SGOT)", aliases=["S.G.O.T (AST)", "SGOT", "SGOT (AST)", "AST", "S.G.O.T", "S G O T"],
        unit="U/L", lo=2, hi=20000, group="liver",
        plain="An enzyme released when liver cells are damaged. High means active injury."),
    "alt": dict(
        display="ALT (SGPT)", aliases=["S.G.P.T (ALT)", "SGPT", "SGPT (ALT)", "ALT", "S.G.P.T", "S G P T"],
        unit="U/L", lo=2, hi=20000, group="liver",
        plain="Like AST, an enzyme released by damaged liver cells, and more specific to the liver."),
    "alp": dict(
        display="Alkaline phosphatase", aliases=["ALP", "ALKALINE PHOSPHATASE", "ALKALINE PHOSPHATASE Serum"],
        unit="U/L", lo=5, hi=3000, group="liver",
        plain="Rises when bile flow out of the liver is obstructed."),
    "protein_total": dict(
        display="Total protein", aliases=["TOTAL PROTEINS", "TOTAL PROTEIN", "TOTAL PROTEINS Serum"],
        unit="g/dL", lo=1.0, hi=12, group="liver",
        plain="All protein in blood. The liver makes most of it."),
    "albumin": dict(
        display="Albumin", aliases=["ALBUMIN", "ALBUMIN Serum", "S ALBUMIN", "SERUM ALBUMIN"],
        unit="g/dL", lo=0.5, hi=6.5, group="liver",
        plain="The main protein the liver makes. Falling albumin means the liver's manufacturing is failing, and it lets fluid leak into the belly and legs."),
    "globulin": dict(
        display="Globulin", aliases=["GLOBULIN", "GLOBULIN Serum"],
        unit="g/dL", lo=0.3, hi=9, group="liver",
        plain="The other main blood protein group, made largely by the immune system."),
    "ag_ratio": dict(
        display="A:G ratio", aliases=["A/G RATIO", "AG RATIO", "A:G RATIO", "ALBUMIN/GLOBULIN RATIO"],
        unit="", lo=0.05, hi=6, group="liver",
        plain="Albumin divided by globulin. Falls as liver function declines."),
    "ammonia": dict(
        display="Ammonia", aliases=["AMMONIA", "AMMONIA LEVELS", "NH3"],
        unit="umol/L", lo=3, hi=1200, group="liver",
        plain="A waste product the liver normally removes. When it builds up it affects the brain, causing confusion and drowsiness."),

    # ---- Coagulation: the liver's clotting output ----
    "pt": dict(
        display="Prothrombin time", aliases=["PROTHROMBIN TIME", "PT", "PROTHROMBIN TIME (PT)"],
        unit="Seconds", lo=5, hi=250, group="coagulation",
        plain="How long blood takes to clot. The liver makes the clotting factors, so this lengthens as the liver fails."),
    "pt_mnpt": dict(
        display="Mean normal PT", aliases=["MEAN NORMAL PROTHROMBIN TIME", "MEAN NORMAL PT", "MNPT"],
        unit="Seconds", lo=7, hi=20, group="coagulation",
        plain="The laboratory's own normal clotting time, used as the yardstick for INR."),
    "inr": dict(
        display="INR", aliases=["INR", "I.N.R", "INTERNATIONAL NORMALIZED RATIO"],
        unit="", lo=0.5, hi=15, group="coagulation",
        plain="Clotting time expressed as a ratio so labs can be compared. Above 1.5 means impaired clotting; it is one of the numbers that drives the MELD score."),
    "aptt": dict(
        display="APTT", aliases=["APTT", "A.P.T.T", "ACTIVATED PARTIAL THROMBOPLASTIN TIME"],
        unit="Seconds", lo=10, hi=250, group="coagulation",
        plain="Another clotting-time measure, covering a different part of the clotting cascade."),
    "fibrinogen": dict(
        display="Fibrinogen", aliases=["FIBRINOGEN", "FIBRINOGEN LEVEL"],
        unit="mg/dL", lo=20, hi=1200, group="coagulation",
        plain="A clotting protein made by the liver. It falls when the liver fails or clotting is being consumed."),

    # ---- Kidney and electrolytes (serum, laboratory) ----
    "creatinine": dict(
        display="Creatinine", aliases=["SERUM CREATININE", "SERUM CREATININE ,", "CREATININE", "S CREATININE"],
        unit="mg/dL", lo=0.05, hi=30, group="kidney",
        plain="A waste product the kidneys filter out. Rising creatinine means the kidneys are struggling, which often follows severe liver disease."),
    "urea": dict(
        display="Blood urea", aliases=["BLOOD UREA", "BLOOD UREA ,", "UREA", "BLOOD UREA Serum"],
        unit="mg/dL", lo=1, hi=500, group="kidney",
        plain="Another waste product cleared by the kidneys."),
    "sodium": dict(
        display="Sodium (serum)", aliases=["SODIUM", "SODIUM ,", "SODIUM Serum", "S SODIUM", "SERUM SODIUM"],
        unit="mEq/L", lo=95, hi=185, group="kidney",
        plain="A salt in blood. It falls in advanced liver disease as the body retains water, and low sodium is a bad sign."),
    "potassium": dict(
        display="Potassium (serum)", aliases=["POTASSIUM", "POTASSIUM ,", "POTASSIUM Serum", "SERUM POTASSIUM"],
        unit="mEq/L", lo=1.0, hi=10, group="kidney",
        plain="A salt that must stay in a narrow band for the heart to beat normally."),
    "chloride": dict(
        display="Chloride (serum)", aliases=["CHLORIDE", "CHLORIDE ,", "CHLORIDE Serum", "CSHLORIDE", "CHLORIDE serum"],
        unit="mEq/L", lo=55, hi=145, group="kidney",
        plain="A salt that moves with sodium and helps track acid-base balance."),
    "calcium": dict(
        display="Calcium (serum)", aliases=["CALCIUM", "SERUM CALCIUM", "TOTAL CALCIUM"],
        unit="mg/dL", lo=2, hi=18, group="kidney",
        plain="Needed for muscle, nerve and clotting function."),
    "phosphorus": dict(
        display="Phosphorus", aliases=["PHOSPHORUS", "SERUM PHOSPHORUS", "PHOSPHOROUS"],
        unit="mg/dL", lo=0.3, hi=16, group="kidney",
        plain="A mineral that shifts with kidney function and nutrition."),
    "magnesium": dict(
        display="Magnesium", aliases=["SERUM MAGNESIUM", "MAGNESIUM"],
        unit="mg/dL", lo=0.3, hi=9, group="kidney",
        plain="A mineral needed for heart rhythm and nerve function."),
    "uric_acid": dict(
        display="Uric acid", aliases=["URIC ACID", "SERUM URIC ACID"],
        unit="mg/dL", lo=0.2, hi=25, group="kidney",
        plain="A waste product cleared by the kidneys."),

    # ---- Blood counts ----
    "hemoglobin": dict(
        display="Haemoglobin", aliases=["HEMOGLOBIN", "HAEMOGLOBIN", "HB", "HGB"],
        unit="g/dL", lo=1.5, hi=25, group="blood",
        plain="The oxygen-carrying pigment in red cells. Low means anaemia or bleeding."),
    "rbc": dict(
        display="RBC count", aliases=["RBC", "RBC COUNT", "TOTAL RBC", "RED BLOOD CELL COUNT"],
        unit="10^6/uL", lo=0.5, hi=9, group="blood",
        plain="How many red blood cells there are."),
    # "HCT" deliberately does NOT appear here. The blood-gas panel prints "Hct"
    # and the blood count prints "PCV", and they are different specimens with
    # different reference ranges (41-51 vs 40.0-50.0). Aliasing both to this key
    # filed blood-gas haematocrit as serum PCV, which then fed the MCV/MCHC
    # identity checks with a value from another instrument. Caught by eye during
    # crop verification: p025 "Hct 31 (L) 41-51" had been recorded as pcv.
    "pcv": dict(
        display="PCV", aliases=["PCV", "PACKED CELL VOLUME"],
        unit="%", lo=4, hi=75, group="blood",
        plain="The share of blood made up of red cells."),
    "mcv": dict(display="MCV", aliases=["MCV"], unit="fL", lo=40, hi=140, group="blood",
        plain="Average red cell size."),
    "mch": dict(display="MCH", aliases=["MCH"], unit="pg", lo=8, hi=55, group="blood",
        plain="Average amount of haemoglobin per red cell."),
    "mchc": dict(display="MCHC", aliases=["MCHC"], unit="g/dL", lo=15, hi=50, group="blood",
        plain="Haemoglobin concentration within red cells."),
    "rdw": dict(display="RDW", aliases=["RDW", "RDW-CV", "RDW CV"], unit="%", lo=5, hi=45, group="blood",
        plain="How much red cell sizes vary."),
    "wbc": dict(
        display="Total WBC", aliases=["TOTAL WBC", "TOTAL LEUCOCYTE COUNT", "TLC", "WBC", "TOTAL WBC COUNT", "AL WBC"],
        # cells/cumm, NOT 10^3/mm^3. This report prints total WBC as an absolute
        # count (11800, reference 4000-10000). Declaring the thousands unit here
        # made the dashboard render "11800 10^3/mm^3" -- a thousandfold
        # overstatement -- because the display unit comes from this dictionary.
        # Platelets genuinely are 10^3/mm^3 (152, reference 150-410); the two
        # look similar and are not.
        unit="cells/cumm", lo=50, hi=200000, group="blood",
        plain="White blood cells, the infection-fighting cells. High usually means infection; very low is also dangerous."),
    "platelets": dict(
        display="Platelet count", aliases=["PLATELET COUNT", "PLATELETS", "PLT"],
        unit="10^3/mm^3", lo=1, hi=2000, group="blood",
        plain="The cells that stop bleeding. They fall in liver disease, raising bleeding risk."),
    "mpv": dict(display="MPV", aliases=["MPV"], unit="fL", lo=3, hi=25, group="blood",
        plain="Average platelet size."),
    "neutrophils_pct": dict(display="Neutrophils %", aliases=["NEUTROPHILS", "NEUTROPHIL", "POLYMORPHS"],
        unit="%", lo=0, hi=100, group="blood",
        plain="Share of white cells that are the main bacteria-fighting type."),
    "lymphocytes_pct": dict(display="Lymphocytes %", aliases=["LYMPHOCYTES", "LYMPHOCYTE"],
        unit="%", lo=0, hi=100, group="blood",
        plain="Share of white cells that fight viruses and coordinate immunity."),
    "monocytes_pct": dict(display="Monocytes %", aliases=["MONOCYTES", "MONOCYTE"],
        unit="%", lo=0, hi=100, group="blood", plain="Share of white cells that clear debris."),
    "eosinophils_pct": dict(display="Eosinophils %", aliases=["EOSINOPHILS", "EOSINOPHIL"],
        unit="%", lo=0, hi=100, group="blood", plain="Share of white cells linked to allergy and parasites."),
    "basophils_pct": dict(display="Basophils %", aliases=["BASOPHILS", "BASOPHIL"],
        unit="%", lo=0, hi=100, group="blood", plain="A small white cell population."),
    "anc": dict(display="Absolute neutrophils", aliases=["ABSOLUTE NEUTROPHIL COUNT", "ABSOLUTE NEUTROPHIL", "ANC"],
        unit="cells/cumm", lo=10, hi=200000, group="blood",
        plain="The actual number of bacteria-fighting cells."),
    "alc": dict(display="Absolute lymphocytes", aliases=["ABSOLUTE LYMPHOCYTE COUNT", "ABSOLUTE LYMPHOCYTE", "ALC"],
        unit="cells/cumm", lo=5, hi=100000, group="blood",
        plain="The actual number of virus-fighting cells."),
    "amc": dict(display="Absolute monocytes", aliases=["ABSOLUTE MONOCYTE COUNT", "ABSOLUTE MONOCYTE"],
        unit="cells/cumm", lo=1, hi=50000, group="blood", plain="The actual number of debris-clearing cells."),
    "aec": dict(display="Absolute eosinophils", aliases=["ABSOLUTE EOSINOPHIL COUNT", "ABSOLUTE EOSINOPHIL"],
        unit="cells/cumm", lo=0, hi=20000, group="blood", plain="The actual number of allergy-linked cells."),
    "abc": dict(display="Absolute basophils", aliases=["ABSOLUTE BASOPHIL COUNT", "ABSOLUTE BASOPHIL"],
        unit="cells/cumm", lo=0, hi=5000, group="blood", plain="The actual number of basophils."),
    "nlr": dict(display="Neutrophil:lymphocyte ratio", aliases=["NEUTROPHIL LYMPHOCYTE RATIO", "NLR", "N/L RATIO"],
        unit="", lo=0.05, hi=300, group="blood",
        plain="Neutrophils divided by lymphocytes. A rising ratio tracks worsening inflammation and predicts outcome in liver failure."),

    # ---- Infection markers ----
    "procalcitonin": dict(
        display="Procalcitonin", aliases=["PROCALCITONIN", "PROCALCITONIN (QUANTITATIVE)", "PCT"],
        unit="ng/mL", lo=0.005, hi=1000, group="infection",
        plain="Rises specifically with bacterial infection. Above 2 suggests severe systemic infection; above 10 suggests septic shock."),
    "crp": dict(display="CRP", aliases=["C REACTIVE PROTEIN", "CRP", "C-REACTIVE PROTEIN", "HS CRP"],
        unit="mg/L", lo=0.05, hi=800, group="infection",
        plain="A general marker of inflammation anywhere in the body."),
    "il6": dict(display="Interleukin-6", aliases=["SERUM IL-6 LEVELS", "IL-6", "IL6", "INTERLEUKIN 6"],
        unit="pg/mL", lo=0.5, hi=100000, group="infection",
        plain="An inflammation signal molecule; very high levels accompany severe systemic inflammation."),

    # ---- Arterial blood gas.  Separate specimen -- never merge with serum. ----
    "abg_ph": dict(display="pH (ABG)", aliases=["pH", "PH"], unit="", lo=6.4, hi=8.0, group="abg",
        plain="How acidic the blood is. It must stay in a very narrow band."),
    "abg_pco2": dict(display="pCO2", aliases=["pCO2", "PCO2", "pco2"], unit="mmHg", lo=5, hi=160, group="abg",
        plain="Carbon dioxide in blood, reflecting breathing."),
    "abg_po2": dict(display="pO2", aliases=["pO2", "PO2", "po2"], unit="mmHg", lo=10, hi=650, group="abg",
        plain="Oxygen dissolved in arterial blood. Low means the lungs are not oxygenating properly."),
    "abg_sodium": dict(display="Na+ (blood gas)", aliases=["Na+", "Nat", "NA+"], unit="mEq/L", lo=95, hi=185, group="abg",
        plain="Sodium measured on the blood-gas machine at the bedside."),
    "abg_potassium": dict(display="K+ (blood gas)", aliases=["K+", "K =", "Kt"], unit="mEq/L", lo=1.0, hi=10, group="abg",
        plain="Potassium measured at the bedside."),
    "abg_chloride": dict(display="Cl- (blood gas)", aliases=["Cl-", "cI-", "Crl-", "CI-", "Cor", "CL-"],
        unit="mEq/L", lo=55, hi=145, group="abg", plain="Chloride measured at the bedside."),
    "abg_calcium": dict(display="Ionised calcium", aliases=["Ca++", "Cat++", "CA++", "Ca++(7.4)", "Cat++(7.4)"],
        unit="mg/dL", lo=1, hi=12, group="abg", plain="The active form of calcium."),
    "abg_hct": dict(display="Hct (blood gas)",
        aliases=["Hct", "Het", "HCT", "HAEMATOCRIT", "HEMATOCRIT"],
        unit="%", lo=4, hi=75, group="abg",
        plain="Red cell share measured at the bedside."),
    "abg_glucose": dict(display="Glucose (blood gas)", aliases=["Glu", "slu", "GLU"], unit="mg/dL", lo=5, hi=1200, group="abg",
        plain="Blood sugar measured at the bedside. A failing liver can let it fall dangerously."),
    "lactate": dict(display="Lactate", aliases=["Lac", "bac", "LAC", "LACTATE", "SERUM LACTATE"],
        unit="mmol/L", lo=0.1, hi=40, group="abg",
        plain="Rises when tissues are not getting enough oxygen or the liver cannot clear it. A key severity marker."),
    "abg_thb": dict(display="Total Hb (co-ox)", aliases=["tHb", "tHb(c)", "THB"], unit="g/dl", lo=1.5, hi=25, group="abg",
        plain="Haemoglobin measured by the blood-gas machine."),
    "abg_o2hb": dict(display="O2Hb", aliases=["O2Hb", "O2HB"], unit="%", lo=0, hi=100, group="abg",
        plain="Share of haemoglobin carrying oxygen."),
    "abg_cohb": dict(display="COHb", aliases=["COHb", "COHB"], unit="%", lo=0, hi=100, group="abg",
        plain="Share of haemoglobin bound to carbon monoxide."),
    "abg_methb": dict(display="MetHb", aliases=["MetHb", "METHB"], unit="%", lo=0, hi=100, group="abg",
        plain="A form of haemoglobin that cannot carry oxygen."),
    "abg_hhb": dict(display="HHb", aliases=["HHb", "HHB"], unit="%", lo=0, hi=100, group="abg",
        plain="Share of haemoglobin not carrying oxygen."),
    "abg_so2": dict(display="sO2", aliases=["sO2", "SO2"], unit="%", lo=0, hi=100, group="abg",
        plain="Oxygen saturation of the blood."),
    "abg_tco2": dict(display="TCO2", aliases=["TCO2", "TCcOo2", "TCO 2"], unit="mmol/L", lo=1, hi=60, group="abg",
        plain="Total carbon dioxide content."),
    "abg_hco3": dict(display="Bicarbonate", aliases=["HCO3-(c)", "HCO3-", "HCO3", "cHCO3-"], unit="mEq/L", lo=1, hi=60, group="abg",
        plain="The blood's acid buffer. Low means acid is building up."),
    "abg_be": dict(display="Base excess", aliases=["BE(B)", "BEecf", "BE ecf", "BE"], unit="mmol/L", lo=-40, hi=40, group="abg",
        plain="How far acid-base balance sits from normal."),
}

# Reverse index: normalised alias -> canonical key. Built once at import.
def _norm(s: str) -> str:
    """Squash a label to its comparison form: alphanumerics only, uppercased."""
    return "".join(ch for ch in s.upper() if ch.isalnum())


ALIAS_TO_KEY = {}
for _key, _meta in ANALYTES.items():
    for _alias in [_meta["display"], *_meta["aliases"]]:
        ALIAS_TO_KEY.setdefault(_norm(_alias), _key)

# --------------------------------------------------------------------------
# Display grouping and the headline set.
# --------------------------------------------------------------------------
GROUPS = {
    "liver": "Liver function",
    "coagulation": "Clotting",
    "kidney": "Kidney and salts",
    "blood": "Blood counts",
    "infection": "Infection markers",
    "abg": "Blood gas",
}

# The five the Summary tab leads with, chosen because they are what actually
# moves the clinical picture in acute liver failure.
HEADLINE = ["bilirubin_total", "inr", "creatinine", "ammonia", "platelets"]

# Direction that means "getting worse", for arrow rendering.
WORSE_WHEN_RISING = {
    "bilirubin_total", "bilirubin_direct", "bilirubin_indirect", "ast", "alt", "alp",
    "ammonia", "pt", "inr", "aptt", "creatinine", "urea", "procalcitonin", "crp",
    "il6", "nlr", "lactate", "potassium", "abg_pco2",
}
WORSE_WHEN_FALLING = {
    "albumin", "protein_total", "ag_ratio", "platelets", "hemoglobin", "pcv",
    "fibrinogen", "sodium", "abg_po2", "abg_so2", "abg_hco3", "abg_glucose",
}

# --------------------------------------------------------------------------
# Palette -- Catppuccin Mocha, per workspace convention.
# Clinical status is encoded by SHAPE as well as colour; colour alone fails for
# colour-blind readers and in print.
# --------------------------------------------------------------------------
PALETTE = {
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    "surface0": "#313244", "surface1": "#45475a", "surface2": "#585b70",
    "text": "#cdd6f4", "subtext": "#a6adc8", "overlay": "#6c7086",
    "red": "#f38ba8", "peach": "#fab387", "yellow": "#f9e2af",
    "green": "#a6e3a1", "teal": "#94e2d5", "blue": "#89b4fa",
    "mauve": "#cba6f7", "lavender": "#b4befe",
}
