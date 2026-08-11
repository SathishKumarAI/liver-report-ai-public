"""Retrieval and prompt tests for src/rag.py. No Ollama, no socket, ever.

Owns: proof that a plain-English question reaches the right chunks, that a date
in the question outranks lexical overlap, that the prompt carries the citation
and safety instructions, and that an unreachable Ollama degrades to a message.

Does NOT own: anything about generation quality -- the model is injected, so
nothing here depends on which model is installed.

Run either way:
    python -m tests.test_rag
    pytest tests/test_rag.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# tests/ is not a package (other agents own files here too), and pytest puts
# tests/ on sys.path rather than the repo root. One line beats a shared conftest.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import rag  # noqa: E402


def _obs(analyte, display, value, day, when, page, unit="", ref=None, flag=None):
    return {"analyte": analyte, "display": display, "sample_id": f"S{day}",
            "collected": when, "day": day, "kind": "quantity", "value": value,
            "text": None, "unit": unit, "reference": ref, "interpretation": flag,
            "printed_flag": flag,
            "provenance": {"page": page, "human_verified": True}}


# Synthetic patient, three days, shaped exactly like docs/SCHEMA.md. Values are
# invented for the test and are not from any report.
DATASET = {
    "patient": {"id": "TEST", "age": 36, "sex": "male"},
    "samples": [
        {"sample_id": "S1", "collected": "2024-03-04T06:00", "panel": "Biochem", "pages": [10, 11]},
        {"sample_id": "S2", "collected": "2024-03-05T06:30", "panel": "Biochem", "pages": [20]},
        {"sample_id": "S3", "collected": "2024-03-06T02:14", "panel": "Coagulation", "pages": [40, 41]},
    ],
    "observations": [
        _obs("inr", "INR", 1.9, 1, "2024-03-04T06:00", 10, "", {"high": 1.3, "text": "Normal <1.3"}, "H"),
        _obs("inr", "INR", 2.4, 2, "2024-03-05T06:30", 20, "", {"high": 1.3, "text": "Normal <1.3"}, "H"),
        _obs("inr", "INR", 2.89, 3, "2024-03-06T02:14", 40, "", {"high": 1.3, "text": "Normal <1.3"}, "H"),
        _obs("bilirubin_total", "Total bilirubin", 3.1, 1, "2024-03-04T06:00", 10, "mg/dL",
             {"low": 0.2, "high": 1.2}, "H"),
        _obs("bilirubin_total", "Total bilirubin", 8.1, 3, "2024-03-06T02:14", 40, "mg/dL",
             {"low": 0.2, "high": 1.2}, "H"),
        _obs("procalcitonin", "Procalcitonin", 4.11, 2, "2024-03-05T06:30", 21, "ng/mL",
             {"high": 0.5}, "H"),
        _obs("creatinine", "Creatinine", 2.4, 2, "2024-03-05T06:30", 22, "mg/dL",
             {"low": 0.7, "high": 1.3}, "H"),
        _obs("sodium", "Sodium (serum)", 128, 3, "2024-03-06T02:14", 41, "mmol/L",
             {"low": 136, "high": 145}, "L"),
        {"analyte": "wbc", "display": "Total WBC", "sample_id": "S3",
         "collected": "2024-03-06T02:14", "day": 3, "kind": "quantity", "value": 18.2,
         "text": None, "unit": "10^3/mm^3", "reference": {"low": 4.0, "high": 11.0},
         "interpretation": "H", "printed_flag": "H",
         "provenance": {"page": 42, "human_verified": True}},
        # Qualitative: a culture. Must never be coerced into a number.
        {"analyte": "procalcitonin", "display": "Blood culture", "sample_id": "S2",
         "collected": "2024-03-05T06:30", "day": 2, "kind": "qualitative", "value": None,
         "text": "Escherichia coli isolated, sensitive to meropenem", "unit": "",
         "reference": None, "interpretation": "A", "printed_flag": None,
         "provenance": {"page": 55, "human_verified": True}},
    ],
    "scores": [
        {"collected": "2024-03-06T02:14", "day": 3,
         "meld3": {"value": 31, "complete": True, "inputs": {"inr": 2.89}},
         "child_pugh": {"value": None, "complete": False,
                        "missing": ["ascites_grade", "encephalopathy_grade"]}},
    ],
    "patterns": [
        {"id": "rising-run", "severity": "high", "analyte": "bilirubin_total",
         "headline": "Bilirubin has risen every day", "detail": "3.1 -> 8.1 mg/dL (04-06 Mar).",
         "evidence": [{"day": 1, "value": 3.1}, {"day": 3, "value": 8.1}],
         "audience": ["doctor", "family"]},
    ],
}


def _ids(hits):
    return [c.id for c, _ in hits]


def test_chunks_cover_every_kind():
    kinds = {c.kind for c in rag.build_chunks(DATASET)}
    assert kinds == {"series", "day", "qualitative", "score", "pattern"}, kinds


def test_series_chunk_holds_the_whole_trend_with_pages():
    inr = next(c for c in rag.build_chunks(DATASET) if c.id == "series:inr")
    for piece in ("1.9", "2.4", "2.89", "04 Mar", "06 Mar"):
        assert piece in inr.text, f"{piece} missing from {inr.text}"
    assert inr.pages == [10, 20, 40]
    assert inr.days == [1, 2, 3]


def test_citations_never_pair_a_page_with_a_date_it_does_not_carry():
    # INR spans pages 10/20/40 on 04/05/06 Mar. Pairing the pages list with the
    # dates list would emit "page 10, 06 Mar", which no page carries. Regression:
    # the first version of _sources did exactly that.
    inr = next(c for c in rag.build_chunks(DATASET) if c.id == "series:inr")
    assert inr.cites == [{"page": 10, "date": "2024-03-04"},
                         {"page": 20, "date": "2024-03-05"},
                         {"page": 40, "date": "2024-03-06"}]

    truth = {(o["provenance"]["page"], o["collected"][:10])
             for o in DATASET["observations"]}
    out = rag.answer("was there any infection?", DATASET, model="m",
                     chat=lambda m, msgs: "ok")
    for c in out["citations"]:
        assert (c["page"], c["date"]) in truth, f"fabricated citation {c}"


def test_prompt_shows_page_and_date_as_a_pair():
    inr = next(c for c in rag.build_chunks(DATASET) if c.id == "series:inr")
    block = rag.build_prompt("inr?", [inr])[-1]["content"]
    assert "page 10 (04 Mar)" in block and "page 40 (06 Mar)" in block


def test_qualitative_result_is_not_turned_into_a_number():
    cult = next(c for c in rag.build_chunks(DATASET) if c.kind == "qualitative")
    assert "Escherichia coli" in cult.text
    assert cult.pages == [55]


def test_incomplete_score_says_what_is_missing():
    score = next(c for c in rag.build_chunks(DATASET) if c.kind == "score")
    assert "child_pugh not computed" in score.text
    assert "encephalopathy_grade" in score.text
    assert "meld3 = 31" in score.text


def test_infection_question_retrieves_procalcitonin_and_culture():
    hits = rag.retrieve("was there any infection?", DATASET, k=4)
    ids = _ids(hits)
    assert "series:procalcitonin" in ids, ids
    assert any(i.startswith("qual:") for i in ids), ids


def test_everyday_words_reach_the_right_analyte():
    assert "series:bilirubin_total" in _ids(rag.retrieve("why is his skin yellow?", DATASET, 3))
    assert "series:creatinine" in _ids(rag.retrieve("how are his kidneys?", DATASET, 3))
    assert "series:inr" in _ids(rag.retrieve("is he at risk of bleeding?", DATASET, 4))


def test_date_mention_boosts_that_day():
    for question in ("what was collected on 06 Mar?", "anything from 06/03?", "how was day 3?"):
        top = _ids(rag.retrieve(question, DATASET, k=3))[0]
        assert top == "day:3", f"{question} -> {top}"
    assert _ids(rag.retrieve("what happened on 4 Mar?", DATASET, k=3))[0] == "day:1"


def test_date_boost_does_not_swamp_a_dateless_question():
    # No date in the question, so a day chunk must not outrank the analyte series.
    assert _ids(rag.retrieve("what is the INR trend?", DATASET, k=3))[0] == "series:inr"


def test_question_about_something_never_measured_retrieves_nothing():
    # Nothing in the record mentions a liver biopsy, so the context must be empty
    # and the model must be steered to "not in the record" rather than to a guess.
    hits = rag.retrieve("what did the liver biopsy show?", DATASET, k=5)
    assert not any(c.kind == "qualitative" for c, _ in hits)
    msgs = rag.build_prompt("what did the liver biopsy show?", [])
    assert "(no matching records)" in msgs[-1]["content"]


def test_prompt_carries_the_citation_and_safety_instructions():
    hits = rag.retrieve("was there any infection?", DATASET, k=3)
    msgs = rag.build_prompt("was there any infection?", [c for c, _ in hits])
    blob = " ".join(m["content"] for m in msgs)
    assert "page number" in blob and "collection date" in blob
    assert "That is not in the record." in blob
    assert "not medical advice" in blob
    assert "diagnosis" in blob and "prognosis" in blob
    assert "page 21 (05 Mar)" in blob or "page 55 (05 Mar)" in blob   # sources labelled
    assert "was there any infection?" in msgs[-1]["content"]


def test_answer_uses_injected_model_and_returns_citations():
    seen = {}

    def fake_chat(model, messages):
        seen["model"] = model
        seen["messages"] = messages
        return "Procalcitonin was 5.03 ng/mL (page 21, 05 Mar)."

    out = rag.answer("was there any infection?", DATASET, model="test-model", chat=fake_chat)
    assert out["ok"] is True
    assert seen["model"] == "test-model"
    assert out["answer"].startswith("Procalcitonin")
    assert {"page": 21, "date": "2024-03-05"} in out["citations"]
    assert all(set(c) >= {"id", "kind", "score"} for c in out["chunks_used"])


def test_ollama_down_degrades_to_a_message_not_a_traceback():
    def dead_chat(model, messages):
        raise rag.OllamaDown("Chat unavailable: cannot reach Ollama at 127.0.0.1:11434. "
                             "Start it with `ollama serve`.")

    out = rag.answer("was there any infection?", DATASET, model="test-model", chat=dead_chat)
    assert out["ok"] is False
    assert "ollama serve" in out["error"]
    assert out["answer"] == ""
    assert out["chunks_used"], "retrieved sources must survive a dead model"


def test_pick_model_prefers_default_and_skips_vision_models():
    assert rag.pick_model(["qwen3vl-2b", "gemma4:12b"]) == "gemma4:12b"
    assert rag.pick_model(["qwen3vl-2b", "minicpm-v4.5", "llama3.2:3b"]) == "llama3.2:3b"
    try:
        rag.pick_model(["qwen3vl-2b", "minicpm-v4.5"])
        raise AssertionError("vision-only install must not be picked")
    except rag.OllamaDown as e:
        assert "ollama pull" in str(e)


def test_endpoint_is_localhost_only():
    assert rag.OLLAMA == "http://127.0.0.1:11434"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")
