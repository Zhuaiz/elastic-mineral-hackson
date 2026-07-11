"""Per-case judge for the mineral-id task (trapstreet contract).

Reads the payload from $TRAPTASK_PAYLOAD, extracts the agent's answer, and
scores 1.0 iff the answer names the correct mineral species. Species names are
normalized (lowercase, punctuation stripped, known synonyms/transliterations
collapsed — creedite/credit, stibnite/antimonite, labradorite/labrador, ...)
so a model answering with a common variant still passes. Hedging answers
("I cannot determine ...") score 0.

Payload contract (same as trapstreet/trapstreet-tasks tasks):
  outputs.case_stdout      -> agent answer (plain text OR {"answer": "..."})
  outputs.case_meta.json   -> {"exit_code": int}
  expected.answer.json     -> {id, answer, accepted[], category, difficulty}
Emits JSON metrics on stdout: {score, agent_answer, expected_answer, ...}.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# 同义词/变体 -> 规范名（与 make_cases.species_synonyms 保持一致，双向收敛）
SYNONYMS = {
    "antimonite": "stibnite", "stibnite": "stibnite",
    "labrador": "labradorite", "labradorite": "labradorite",
    "nephritis": "nephrite", "nephrite": "nephrite",
    "credit": "creedite", "creedite": "creedite",
    "cobaltin": "cobaltite", "cobaltite": "cobaltite",
    "analcim": "analcime", "analcite": "analcime", "analcime": "analcime",
    "cancrinit": "cancrinite", "cancrinite": "cancrinite",
    "elbait": "elbaite", "elbaite": "elbaite",
    "scheelit": "scheelite", "scheelite": "scheelite",
    "vesuvian": "vesuvianite", "idocrase": "vesuvianite", "vesuvianite": "vesuvianite",
    "sphene": "titanite", "titanite": "titanite",
    "fluorspar": "fluorite", "fluorite": "fluorite",
    "baryte": "barite", "barite": "barite",
}

HEDGES = [
    "i cannot", "i can't", "i am unable", "i'm unable", "cannot determine",
    "unable to determine", "i don't know", "i do not know", "as an ai",
    "not enough information", "insufficient information", "unclear",
]


def normalize(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"^\s*(?:answer|species|a)\s*[:\-]\s*", "", s)  # 去 "Answer:" 前缀
    s = re.sub(r"[^a-z\s-]", "", s)
    first = s.split("\n")[0].strip()
    # 取词元里第一个已知种名（模型可能写 "the mineral is malachite"）
    tokens = [t for t in re.split(r"\s+", first) if t]
    for t in tokens:
        if t in SYNONYMS:
            return SYNONYMS[t]
    tok = tokens[0] if tokens else ""
    return SYNONYMS.get(tok, tok)


def extract_answer(stdout: str) -> str:
    stdout = stdout.strip()
    if not stdout:
        return ""
    try:
        obj = json.loads(stdout)
        if isinstance(obj, dict) and "answer" in obj:
            return str(obj["answer"])
    except json.JSONDecodeError:
        pass
    return stdout


def is_hedge(text: str) -> bool:
    low = re.sub(r"\s+", " ", text).strip().lower()
    return any(h in low for h in HEDGES)


def accepted_forms(expected: dict) -> set[str]:
    """所有可接受的书写形式（规范名 + 声明的同义词 + 它们的原始拼写）。"""
    forms = {normalize(expected["answer"]), expected["answer"].strip().lower()}
    for a in expected.get("accepted") or []:
        forms.add(normalize(a))
        forms.add(a.strip().lower())
    return forms


def whole_word_hit(answer: str, forms: set[str]) -> bool:
    """短答案里，任一可接受形式作为完整词出现即算命中（对齐 keywords_any_word）。
    限制词数以防模型把候选清单整个 dump 出来蒙混。"""
    low = re.sub(r"[^a-z\s-]", " ", answer.lower())
    if len(low.split()) > 8:
        return False
    return any(re.search(rf"\b{re.escape(f)}\b", low) for f in forms if f)


def main() -> None:
    payload = json.loads(os.environ["TRAPTASK_PAYLOAD"])
    stdout = Path(payload["outputs"]["case_stdout"]).read_text()
    exit_code = json.loads(Path(payload["outputs"]["case_meta.json"]).read_text())["exit_code"]
    expected = json.loads(Path(payload["expected"]["answer.json"]).read_text())

    base = {
        "agent_answer": extract_answer(stdout),
        "expected_answer": expected.get("answer"),
        "id": expected.get("id"),
        "category": expected.get("category"),
        "difficulty": expected.get("difficulty"),
    }

    if exit_code != 0:
        print(json.dumps({"score": 0.0, "reason": f"solution exited {exit_code}", **base}))
        return
    answer = base["agent_answer"]
    if not answer:
        print(json.dumps({"score": 0.0, "reason": "empty answer", **base}))
        return
    if is_hedge(answer):
        print(json.dumps({"score": 0.0, "reason": "hedged answer", **base}))
        return

    forms = accepted_forms(expected)
    got = normalize(answer)
    ok = got in forms or whole_word_hit(answer, forms)
    print(json.dumps({
        "score": 1.0 if ok else 0.0,
        "reason": f"answer {answer.strip()[:40]!r} " + ("matched" if ok else "≠")
                  + f" {normalize(expected['answer'])!r}",
        **base,
    }))


if __name__ == "__main__":
    main()
