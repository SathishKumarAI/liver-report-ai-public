"""Record which values a human has confirmed against the page image.

The ledger is data/review.json, keyed "page:analyte". build.py reads it and
sets provenance.human_verified, and refuses to export in strict mode while any
charted value is still unconfirmed.

Kept as an explicit, reviewable file rather than a flag inside the dataset so
that regenerating the dataset never silently marks anything as verified.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as C

LEDGER = C.DATA / "review.json"


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"verified": {}, "notes": []}


def main(argv: list[str]) -> int:
    dataset = json.loads(C.LABS_JSON.read_text())
    ledger = load()

    if "--sheets" in argv:
        wanted = {int(x) for x in argv[argv.index("--sheets") + 1].split(",")}
        index = json.loads((C.DATA / "verify" / "index.json").read_text())
        analytes = set()
        for sheet in index:
            if sheet["sheet"] in wanted:
                analytes |= set(sheet["analytes"])
        targets = [o for o in dataset["observations"] if o["analyte"] in analytes]
        reason = f"contact sheets {sorted(wanted)} read against the page crops"
    elif "--pages" in argv:
        pages = {int(x) for x in argv[argv.index("--pages") + 1].split(",")}
        targets = [o for o in dataset["observations"] if o["page"] in pages]
        reason = f"pages {sorted(pages)} read in full against the page image"
    elif "--disagreements" in argv:
        targets = [o for o in dataset["observations"]
                   if len({v for v in o["provenance"]["ocr"].values() if v is not None}) > 1]
        reason = "every value whose OCR passes disagreed, read individually"
    else:
        print(__doc__)
        print("usage: --sheets 8,9,10 | --pages 21,40 | --disagreements")
        return 1

    added = 0
    for o in targets:
        if o.get("value") is None:
            continue
        key = f"{o['page']}:{o['analyte']}"
        if key not in ledger["verified"]:
            added += 1
        ledger["verified"][key] = {
            "value": o["value"], "on": date.today().isoformat(), "how": reason,
        }

    ledger["notes"] = sorted(set(ledger.get("notes", []) + [reason]))
    LEDGER.write_text(json.dumps(ledger, indent=1))

    total = sum(1 for o in dataset["observations"] if o.get("value") is not None)
    print(f"marked        : +{added}")
    print(f"ledger total  : {len(ledger['verified'])} of {total} charted values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
