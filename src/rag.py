"""Local retrieval-augmented chat over one patient's verified lab dataset.

Owns: turning labs.json into retrievable text chunks, lexical (BM25) retrieval
with analyte-synonym expansion and date boosting, the grounded prompt, and the
localhost-only Ollama call.

Does NOT own: extraction, scoring, pattern detection, rendering. It only reads
the finished dataset. It never computes a clinical number and never invents one:
if a value is not in the dataset it cannot be in the answer.

Why lexical retrieval and not embeddings: one patient's record is a few hundred
chunks. BM25 over that is exact, instant and auditable -- you can see WHICH term
pulled a chunk in. An embedding model would be a download, a vector store and a
similarity nobody can explain, to rank 300 strings.

ponytail: index rebuilt per call, scored by full scan, O(chunks x terms) --
microseconds at this size. Upgrade path if a multi-patient corpus ever lands
here: one persistent inverted index, or a local embedding reranker over the
top-k this already returns.
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from . import config as C

# The ONLY endpoint this module may ever touch. PHI does not leave the machine;
# _post asserts the host rather than trusting the caller.
# ponytail: kept here, not in config.py, because nothing else in src/ talks to
# Ollama. Move it to config the moment a second module needs it.
OLLAMA = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:12b"

# Tried in order. MedGemma is Google's OPEN-WEIGHT medical model -- it runs here
# on the local Ollama like any other, so preferring it costs nothing and it is
# tuned for exactly this material.
#
# Note the deliberate absence of any hosted model. A Gemini or Claude API call
# would send this patient's labs off the machine, which is the one thing this
# project may not do. "Best medical model" here means best model that can run
# locally, and that is MedGemma.
PREFERRED_MODELS = (
    "alibayram/medgemma:4b",
    "medgemma",              # any locally-tagged MedGemma build
    "gemma4:12b",
)
# Substrings that mark a vision model. Those answer text questions badly and are
# not what a lab-record chat wants.
VISION_HINTS = ("vl", "vision", "llava", "minicpm-v", "bakllava", "moondream")

TIMEOUT = 300  # a 12B model on CPU is slow; a short timeout would read as "down"

# Measured, not guessed: at Ollama's default 4096 the retrieved context plus
# gemma4's hidden reasoning hit the limit and the reply came back EMPTY
# (done_reason "length", 10k characters of thinking, zero characters of answer).
# `think: false` in _chat_body is the other half of that fix.
NUM_CTX = 8192


class OllamaDown(RuntimeError):
    """Ollama is not reachable, has no usable model, or produced nothing.
    The message is user-facing: it must say what to do, not what broke."""
    status: int | None = None


# --------------------------------------------------------------------------
# Chunking. One retrievable fact-cluster per chunk, each carrying the metadata
# the answer must cite: pages and collection dates.
# --------------------------------------------------------------------------
@dataclass
class Chunk:
    id: str
    kind: str                                   # series|day|qualitative|score|pattern
    text: str
    analytes: list[str] = field(default_factory=list)
    days: list[int] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)   # "2024-03-06"
    pages: list[int] = field(default_factory=list)
    # Page and date as they actually occurred TOGETHER, one entry per source
    # observation. Never derive a citation by pairing the pages list with the
    # dates list: a series chunk spans several of each, and the cross product
    # invents provenance that no page carries ("page 10, 06 Mar" for a value
    # printed on page 10 on the 4th).
    cites: list[dict] = field(default_factory=list)


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _date(iso: str) -> str:
    return iso[:10]


def _label(iso: str, with_time: bool) -> str:
    d = _dt(iso)
    return d.strftime("%d %b %H:%M") if with_time else d.strftime("%d %b")


def _ref_text(ref: dict | None) -> str:
    if not ref:
        return "no reference range printed"
    if ref.get("text"):
        return str(ref["text"])
    lo, hi = ref.get("low"), ref.get("high")
    if lo is not None and hi is not None:
        return f"reference {lo} - {hi}"
    if hi is not None:
        return f"reference <{hi}"
    if lo is not None:
        return f"reference >{lo}"
    return "no reference range printed"


def _pages_of(obs_list: list[dict]) -> list[int]:
    return sorted({o.get("provenance", {}).get("page") for o in obs_list
                   if o.get("provenance", {}).get("page")})


def _obs_cites(obs_list: list[dict]) -> list[dict]:
    """The (page, date) pairs that actually occurred, one per source observation.

    Provenance is taken per observation, not from the sample's page list, so a
    citation always points at the page the number is literally printed on.
    """
    seen, out = set(), []
    for o in obs_list:
        page = o.get("provenance", {}).get("page")
        key = (page, _date(o["collected"]) if o.get("collected") else None)
        if page and key not in seen:
            seen.add(key)
            out.append({"page": key[0], "date": key[1]})
    return sorted(out, key=lambda c: (c["page"], c["date"] or ""))


def _by_day(dataset: dict) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for o in dataset.get("observations", []):
        if o.get("day"):
            grouped[o["day"]].append(o)
    return grouped


def _series_chunks(dataset: dict) -> list[Chunk]:
    """One chunk per analyte: the whole time series in one retrievable string.

    The plain-language sentence from config goes in the text on purpose -- it is
    what makes "why is he yellow" land on bilirubin without any query rewriting.
    """
    by_analyte: dict[str, list[dict]] = defaultdict(list)
    for o in dataset.get("observations", []):
        if o.get("kind") == "quantity" and o.get("value") is not None:
            by_analyte[o["analyte"]].append(o)

    chunks = []
    for key, obs in by_analyte.items():
        obs.sort(key=lambda o: o.get("collected", ""))
        per_day = Counter(_date(o["collected"]) for o in obs)
        parts = [f"{o['value']} ({_label(o['collected'], per_day[_date(o['collected'])] > 1)})"
                 for o in obs]
        meta = C.ANALYTES.get(key, {})
        unit = obs[0].get("unit") or "no units"
        flags = sorted({o["interpretation"] for o in obs if o.get("interpretation")})
        text = (
            f"{obs[0].get('display', key)} ({key}), {C.GROUPS.get(meta.get('group'), 'other')}. "
            f"Values over time: {', '.join(parts)}. "
            f"Units {unit}. {_ref_text(obs[0].get('reference'))}. "
            f"Flags printed by the lab: {', '.join(flags) or 'none'}. "
            f"{meta.get('plain', '')}"
        )
        chunks.append(Chunk(
            id=f"series:{key}", kind="series", text=text, analytes=[key],
            days=sorted({o["day"] for o in obs if o.get("day")}),
            dates=sorted({_date(o["collected"]) for o in obs}),
            pages=_pages_of(obs), cites=_obs_cites(obs),
        ))
    return chunks


def _day_chunks(dataset: dict) -> list[Chunk]:
    """One chunk per day: everything collected that day, for 'what about the 6th'."""
    chunks = []
    for day, obs in sorted(_by_day(dataset).items()):
        dates = sorted({_date(o["collected"]) for o in obs if o.get("collected")})
        stamp = _dt(obs[0]["collected"]).strftime("%d %b %Y") if obs[0].get("collected") else ""
        lines = []
        for o in sorted(obs, key=lambda o: o.get("display", "")):
            shown = o.get("text") if o.get("kind") == "qualitative" else o.get("value")
            flag = f" [{o['interpretation']}]" if o.get("interpretation") else ""
            lines.append(f"{o.get('display', o['analyte'])} {shown} {o.get('unit', '')}{flag}".strip())
        text = (f"Day {day} ({stamp}) -- everything collected that day. "
                f"{'; '.join(lines)}.")
        chunks.append(Chunk(id=f"day:{day}", kind="day", text=text,
                            analytes=sorted({o["analyte"] for o in obs}),
                            days=[day], dates=dates, pages=_pages_of(obs),
                            cites=_obs_cites(obs)))
    return chunks


def _qualitative_chunks(dataset: dict) -> list[Chunk]:
    """Cultures, serology, smears: text results that must never become numbers."""
    chunks = []
    for i, o in enumerate(dataset.get("observations", [])):
        if o.get("kind") != "qualitative":
            continue
        page = o.get("provenance", {}).get("page")
        text = (f"{o.get('display', o['analyte'])} result: {o.get('text')}. "
                f"Collected {_label(o['collected'], True)} (day {o.get('day')}). "
                f"{C.ANALYTES.get(o['analyte'], {}).get('plain', '')}")
        chunks.append(Chunk(id=f"qual:{o['analyte']}:{i}", kind="qualitative", text=text,
                            analytes=[o["analyte"]],
                            days=[o["day"]] if o.get("day") else [],
                            dates=[_date(o["collected"])] if o.get("collected") else [],
                            pages=[page] if page else [], cites=_obs_cites([o])))
    return chunks


def _score_chunks(dataset: dict) -> list[Chunk]:
    """One chunk per day's scores. Incomplete scores state what is missing -- the
    chat must be able to say 'not computed, because X was never recorded'."""
    by_day = _by_day(dataset)
    chunks = []
    for s in dataset.get("scores", []):
        day = s.get("day")
        parts = []
        for name, body in s.items():
            if not isinstance(body, dict):
                continue
            if body.get("complete") and body.get("value") is not None:
                parts.append(f"{name} = {body['value']}")
            else:
                missing = ", ".join(body.get("missing", [])) or "unrecorded inputs"
                parts.append(f"{name} not computed: missing {missing}")
        stamp = _dt(s["collected"]).strftime("%d %b %Y") if s.get("collected") else ""
        text = f"Severity scores for day {day} ({stamp}): {'; '.join(parts)}."
        obs = by_day.get(day, [])   # a score is cited to the pages of its inputs
        chunks.append(Chunk(id=f"score:{day}", kind="score", text=text, days=[day] if day else [],
                            dates=[_date(s["collected"])] if s.get("collected") else [],
                            pages=_pages_of(obs), cites=_obs_cites(obs)))
    return chunks


def _pattern_chunks(dataset: dict) -> list[Chunk]:
    chunks = []
    for i, p in enumerate(dataset.get("patterns", [])):
        days = sorted({e["day"] for e in p.get("evidence", []) if e.get("day")})
        key = p.get("analyte")
        # Cite only the pages where THIS analyte was printed on the evidence
        # days, not everything else collected the same day.
        obs = [o for o in dataset.get("observations", [])
               if o.get("day") in days and (key is None or o.get("analyte") == key)]
        text = (f"Detected pattern ({p.get('severity')}): {p.get('headline')}. "
                f"{p.get('detail', '')} Analyte: {key}. "
                f"{C.ANALYTES.get(key, {}).get('plain', '')}")
        chunks.append(Chunk(id=f"pattern:{p.get('id')}:{i}", kind="pattern", text=text,
                            analytes=[key] if key else [], days=days,
                            dates=sorted({_date(o["collected"]) for o in obs
                                          if o.get("collected")}),
                            pages=_pages_of(obs), cites=_obs_cites(obs)))
    return chunks


def build_chunks(dataset: dict) -> list[Chunk]:
    return (_series_chunks(dataset) + _day_chunks(dataset) + _qualitative_chunks(dataset)
            + _score_chunks(dataset) + _pattern_chunks(dataset))


# --------------------------------------------------------------------------
# Query understanding: everyday words -> canonical analyte vocabulary.
# --------------------------------------------------------------------------
STOP = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "in", "on", "at",
    "to", "for", "it", "he", "she", "his", "her", "him", "any", "there", "did", "do",
    "does", "has", "have", "had", "what", "when", "why", "how", "which", "that", "this",
    "with", "from", "by", "as", "be", "been", "so", "if", "not", "no", "but", "can",
    "about", "me", "my", "you", "we", "they", "them", "than", "then", "its", "i",
}
_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in STOP and len(t) > 1]


def _concept_index() -> dict[str, set[str]]:
    """word -> analyte keys, built from the display name, aliases and the plain
    sentence in config. This is the whole synonym table: "kidneys" is in
    creatinine's plain text, "infection" is in procalcitonin's, so the mapping
    maintains itself when a new analyte is added to config."""
    idx: dict[str, set[str]] = defaultdict(set)
    for key, meta in C.ANALYTES.items():
        blob = " ".join([key.replace("_", " "), meta["display"], *meta["aliases"], meta["plain"]])
        for w in set(tokens(blob)):
            idx[w].add(key)
    return dict(idx)


CONCEPTS = _concept_index()

# Words a family or a nurse uses that no config sentence happens to contain.
# Deliberately tiny: everything derivable from config is derived, not typed.
EVERYDAY = {
    "jaundice": ["bilirubin_total", "bilirubin_direct"],
    "jaundiced": ["bilirubin_total"],
    "confused": ["ammonia"], "drowsy": ["ammonia"], "sleepy": ["ammonia"],
    "encephalopathy": ["ammonia"], "coma": ["ammonia"],
    "sepsis": ["procalcitonin", "crp", "wbc"], "septic": ["procalcitonin", "crp", "wbc"],
    "fever": ["procalcitonin", "crp", "wbc"], "infected": ["procalcitonin", "crp", "wbc"],
    "infection": ["procalcitonin", "crp", "wbc"],
    # "bleeding" is in haemoglobin's and platelets' plain text but not the
    # clotting analytes', and a bleeding-risk question is really about those.
    "bleeding": ["inr", "pt", "platelets"], "bleed": ["inr", "pt", "platelets"],
    "clotting": ["inr", "pt", "platelets"],
    "kidneys": ["creatinine", "urea"], "renal": ["creatinine", "urea"],
}
# Free-text terms worth adding to the query alongside analyte keys, because the
# matching chunk is a qualitative result rather than an analyte series.
EVERYDAY_TERMS = {
    "infection": ["culture", "growth", "sepsis"],
    "sepsis": ["culture", "growth"],
    "fever": ["culture", "growth"],
    "infected": ["culture", "growth"],
}

# A word matching more than this many analytes ("blood", "cells") carries no
# signal, so it does not expand. Measured against config: "kidney" hits 4,
# "clotting" hits 6, "blood" hits 20+.
MAX_FANOUT = 8
EXPANSION_WEIGHT = 0.6


def expand(question: str) -> dict[str, float]:
    """Query terms with weights: the literal words, plus canonical vocabulary
    pulled in by synonym expansion at a lower weight."""
    q: dict[str, float] = {}
    for t in tokens(question):
        q[t] = max(q.get(t, 0.0), 1.0)
    for t in list(q):
        extra = list(EVERYDAY.get(t, []))
        keys = CONCEPTS.get(t, set())
        if len(keys) <= MAX_FANOUT:
            extra += list(keys)
        for key in extra:
            for w in tokens(key.replace("_", " ") + " " + C.ANALYTES.get(key, {}).get("display", "")):
                q[w] = max(q.get(w, 0.0), EXPANSION_WEIGHT)
        for w in EVERYDAY_TERMS.get(t, []):
            q[w] = max(q.get(w, 0.0), EXPANSION_WEIGHT)
    return q


_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def mentioned_dates(question: str) -> tuple[set[tuple[int, int]], set[int]]:
    """(day-of-month, month) pairs and explicit 'day N' indices in a question.

    Year is ignored: one admission, one year, and "the 6th" must still work.
    """
    q = question.lower()
    dm: set[tuple[int, int]] = set()
    for d, mon in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([a-z]{3,9})\b", q):
        if mon[:3] in _MONTHS:
            dm.add((int(d), _MONTHS[mon[:3]]))
    for mon, d in re.findall(r"\b([a-z]{3,9})[\s-]+(\d{1,2})(?:st|nd|rd|th)?\b", q):
        if mon[:3] in _MONTHS:
            dm.add((int(d), _MONTHS[mon[:3]]))
    for d, m in re.findall(r"\b(\d{1,2})[/-](\d{1,2})\b", q):          # dd/mm, Indian order
        dm.add((int(d), int(m)))
    for y, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", q):
        dm.add((int(d), int(m)))
    days = {int(d) for d in re.findall(r"\bday\s*(\d{1,2})\b", q)}
    return dm, days


# A date-matching chunk is multiplied and then floored, because "what was
# collected on the 6th" has almost no lexical overlap with any chunk -- the
# question is entirely about the date. The day chunk gets the larger floor: when
# a question names a date and nothing else, the day summary IS the answer, and
# without this the shorter score chunk wins on BM25 length normalisation alone.
DATE_MULT = 2.0
DATE_FLOOR = 2.0
DAY_CHUNK_FLOOR = 3.0


class Index:
    """BM25 over the chunk texts. k1/b are the standard defaults; nothing in
    this corpus justifies tuning them."""

    K1 = 1.5
    B = 0.75

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.tf = [Counter(tokens(c.text)) for c in chunks]
        self.lens = [sum(t.values()) for t in self.tf] or [0]
        self.avg = sum(self.lens) / len(self.lens) if chunks else 1.0
        self.df: Counter = Counter()
        for t in self.tf:
            self.df.update(t.keys())

    def _idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self.df.get(term, 0)
        # +1 inside the log keeps this non-negative for terms in most documents.
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, question: str, k: int = 8) -> list[tuple[Chunk, float]]:
        query = expand(question)
        dm, day_nums = mentioned_dates(question)
        scored: list[tuple[Chunk, float]] = []
        for i, chunk in enumerate(self.chunks):
            tf, dl = self.tf[i], self.lens[i]
            s = 0.0
            for term, weight in query.items():
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + self.K1 * (1 - self.B + self.B * dl / (self.avg or 1))
                s += weight * self._idf(term) * (f * (self.K1 + 1)) / denom
            if self._date_hit(chunk, dm, day_nums):
                s = s * DATE_MULT + (DAY_CHUNK_FLOOR if chunk.kind == "day" else DATE_FLOOR)
            if s > 0:
                scored.append((chunk, s))
        scored.sort(key=lambda cs: (-cs[1], cs[0].id))
        return scored[:k]

    @staticmethod
    def _date_hit(chunk: Chunk, dm: set[tuple[int, int]], days: set[int]) -> bool:
        if days & set(chunk.days):
            return True
        return any((int(d[8:10]), int(d[5:7])) in dm for d in chunk.dates)


def retrieve(question: str, dataset: dict, k: int = 8) -> list[tuple[Chunk, float]]:
    return Index(build_chunks(dataset)).search(question, k)


# --------------------------------------------------------------------------
# Prompt. The instructions are the safety mechanism, so they are explicit,
# ordered, and repeated in the user turn where models attend to them best.
# --------------------------------------------------------------------------
SYSTEM = """You are a careful assistant reading extracts from ONE patient's hospital laboratory record.

Rules, in order of importance:
1. Answer ONLY from the LAB DATA provided in the user message. Use no outside knowledge, no typical values, no textbook ranges that are not printed in the data.
2. Cite every single claim with the page number and the collection date it came from, in the form (page 40, 06 Mar).
3. If the data does not contain the answer, say "That is not in the record." Do not guess, estimate or interpolate a missing value.
4. Never offer a diagnosis, a cause, a treatment or a prognosis, and never say what will happen next. Report what was measured and how it changed.
5. Quote numbers exactly as given, with their units.
6. End your reply with this sentence on its own line: This is a summary of recorded lab values, not medical advice."""


def build_prompt(question: str, chunks: list[Chunk]) -> list[dict]:
    blocks = []
    for c in chunks:
        # Page and date shown as a pair, so the model does not have to guess
        # which date a page belongs to -- and cannot pair them wrongly.
        src = ", ".join(f"page {x['page']} ({_dt(x['date']).strftime('%d %b')})"
                        if x.get("date") else f"page {x['page']}" for x in c.cites)
        blocks.append(f"[{c.id} | source: {src or 'page unknown'}]\n{c.text}")
    data = "\n\n".join(blocks) or "(no matching records)"
    user = (f"LAB DATA:\n\n{data}\n\n"
            f"QUESTION: {question}\n\n"
            f"Answer only from the LAB DATA above. Cite page number and collection date for "
            f"every claim. If it is not there, say \"That is not in the record.\"")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------
# Ollama, localhost only.
# --------------------------------------------------------------------------
def _post(path: str, payload: dict | None = None, stream: bool = False):
    url = OLLAMA + path
    assert url.startswith("http://127.0.0.1:11434"), "PHI may only be sent to localhost Ollama"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        err = OllamaDown(f"Chat unavailable: Ollama refused the request (HTTP {e.code}). "
                         f"Check the model name with `ollama list`.")
        err.status = e.code
        raise err from None
    except (urllib.error.URLError, OSError) as e:
        raise OllamaDown(
            "Chat unavailable: cannot reach Ollama at 127.0.0.1:11434. "
            "Start it with `ollama serve`, then reload this page. "
            f"({type(e).__name__})") from None
    return resp if stream else json.loads(resp.read())


def list_models() -> list[str]:
    return [m["name"] for m in _post("/api/tags").get("models", [])]


def pick_model(models: list[str] | None = None) -> str:
    """Prefer a medical model, then the default, then any installed text model."""
    names = list_models() if models is None else models
    for want in PREFERRED_MODELS:
        for n in names:
            if n == want or want in n.lower():
                return n
    for n in names:
        if not any(h in n.lower() for h in VISION_HINTS):
            return n
    raise OllamaDown(
        "Chat unavailable: no text model installed in Ollama. "
        f"Run `ollama pull {DEFAULT_MODEL}`.")


def _chat_body(model: str, messages: list[dict], stream: bool, think: bool | None) -> dict:
    body = {"model": model, "messages": messages, "stream": stream,
            "options": {"temperature": 0, "num_ctx": NUM_CTX}}
    if think is not None:
        body["think"] = think
    return body


def _ollama_chat(model: str, messages: list[dict]) -> str:
    try:
        body = _post("/api/chat", _chat_body(model, messages, False, think=False))
    except OllamaDown as e:
        if e.status != 400:      # older Ollama / non-thinking model rejects "think"
            raise
        body = _post("/api/chat", _chat_body(model, messages, False, think=None))
    text = (body.get("message", {}).get("content") or "").strip()
    if not text:
        raise OllamaDown(
            f"Chat unavailable: {model} returned no answer (it ran out of context "
            f"before replying). Ask a narrower question, or `ollama pull` a smaller model.")
    return text


def _ollama_stream(model: str, messages: list[dict]):
    resp = _post("/api/chat", _chat_body(model, messages, True, think=False), stream=True)
    for line in resp:
        if not line.strip():
            continue
        piece = json.loads(line).get("message", {}).get("content", "")
        if piece:
            yield piece


def _sources(hits: list[tuple[Chunk, float]]) -> tuple[list[dict], list[dict]]:
    citations, used, seen = [], [], set()
    for chunk, score in hits:
        used.append({"id": chunk.id, "kind": chunk.kind, "score": round(score, 3),
                     "pages": chunk.pages, "dates": chunk.dates, "cites": chunk.cites})
        for c in chunk.cites:
            key = (c["page"], c["date"])
            if key not in seen:
                seen.add(key)
                citations.append(dict(c))
    citations.sort(key=lambda c: (c["page"], c["date"] or ""))
    return citations, used


def answer(question: str, dataset: dict, model: str | None = None,
           chat=None, k: int = 8) -> dict:
    """Retrieve, prompt, generate. `chat` is injectable so tests never open a socket.

    Never raises for an unreachable model: the dashboard shows `error` and stays
    usable. The retrieved chunks are returned either way, so "chat is down" still
    shows the user which records their question matched.
    """
    hits = retrieve(question, dataset, k)
    citations, used = _sources(hits)
    messages = build_prompt(question, [c for c, _ in hits])
    try:
        model = model or pick_model()
        text = (chat or _ollama_chat)(model, messages)
    except OllamaDown as e:
        return {"ok": False, "error": str(e), "answer": "", "model": model,
                "citations": citations, "chunks_used": used}
    return {"ok": True, "error": None, "answer": text, "model": model,
            "citations": citations, "chunks_used": used}


def answer_stream(question: str, dataset: dict, model: str | None = None, k: int = 8):
    """Yields text pieces. Same contract as answer(); the caller collects sources
    from retrieve() itself if it needs them mid-stream."""
    hits = retrieve(question, dataset, k)
    messages = build_prompt(question, [c for c, _ in hits])
    try:
        yield from _ollama_stream(model or pick_model(), messages)
    except OllamaDown as e:
        yield str(e)


if __name__ == "__main__":
    # Self-check against the real dataset if it exists; otherwise just prove the
    # retrieval path runs. Deliberately makes no model call.
    if C.LABS_JSON.exists():
        ds = json.loads(C.LABS_JSON.read_text(encoding="utf-8"))
        for q in ["was there any infection?", "why is he yellow?", "what about 06 Mar?"]:
            top = retrieve(q, ds, 3)
            print(q, "->", [c.id for c, _ in top])
    else:
        print(f"{C.LABS_JSON} not built yet; run tests/test_rag.py instead")
