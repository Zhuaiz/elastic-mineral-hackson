"""生成 trapstreet 官方格式的矿物鉴定任务。

产物（对齐 trapstreet/trapstreet-tasks 的 plant_disease_id 布局）：
  traptask.yaml            dirs + cases[] + judge/grader cmd
  inputs/<id>/question.txt 属性观察 + 98 候选种清单 + 作答说明
  expected/<id>/answer.json {id, answer, matchers, category, difficulty}

设计：闭集分类（给出 98 候选种），题面只含可观察属性、不含化学式。
判分交给 judge.py（种名归一化后精确匹配 + 拒绝 hedge）。

用法: python3 trap/task/make_cases.py
"""
import json
import random
import re
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
ROOT = TASK_DIR.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from config import PROPS_DIR, all_canonical_names  # noqa: E402

N_CASES = 50
rng = random.Random(42)


def short(value: str, words: int = 5) -> str:
    if not value:
        return ""
    return " ".join(re.split(r"[,.;]", value)[0].split()[:words]).strip()


def build_clues(rec: dict) -> str:
    bits = []
    if rec["crystal_system"]:
        bits.append(f"crystal system {rec['crystal_system'].lower()}")
    hmin, hmax = rec["hardness_min"], rec["hardness_max"]
    if hmin:
        bits.append(f"Mohs hardness {hmin}" + (f"-{hmax}" if hmax and hmax != hmin else ""))
    if rec["streak"]:
        bits.append(f"{short(rec['streak'], 3).lower()} streak")
    if rec["color"]:
        bits.append(f"color {short(rec['color'], 5).lower()}")
    if rec["luster"]:
        bits.append(f"{short(rec['luster'], 3).lower()} luster")
    if rec["diaphaneity"]:
        bits.append(short(rec["diaphaneity"], 2).lower())
    if rec["density"]:
        bits.append(f"specific gravity about {rec['density']}")
    return "; ".join(bits)


def difficulty_of(rec: dict) -> str:
    """诊断性强的（金属光泽或彩色条痕）好认=easy；白条痕玻璃透明的一堆像=hard。"""
    luster = (rec["luster"] or "").lower()
    streak = (rec["streak"] or "").lower()
    if "metallic" in luster or (streak and "white" not in streak and "colourless" not in streak):
        return "easy"
    if "white" in streak and "vitreous" in luster:
        return "hard"
    return "medium"


def main() -> None:
    props = json.load(open(PROPS_DIR / "minerals.json"))
    candidates = all_canonical_names()
    choose_from = ", ".join(candidates)

    usable = {k: v for k, v in props.items()
              if v["crystal_system"] and v["hardness_min"] and v["streak"] and v["color"]}
    species_list = rng.sample(sorted(usable), min(N_CASES, len(usable)))

    inputs_dir = TASK_DIR / "inputs"
    expected_dir = TASK_DIR / "expected"
    for d in (inputs_dir, expected_dir):
        if d.exists():
            import shutil
            shutil.rmtree(d)
    cases_meta = []

    for name in species_list:
        rec = usable[name]
        case_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        clues = build_clues(rec)
        question = (
            "A field geologist recorded these hand-specimen observations of an "
            f"unknown mineral:\n\n{clues}.\n\n"
            f"Identify the mineral species. Choose from:\n{choose_from}\n\n"
            "Answer with the exact species name from the list only, one lowercase "
            "word. Do not hedge or explain."
        )
        (inputs_dir / case_id).mkdir(parents=True, exist_ok=True)
        (inputs_dir / case_id / "question.txt").write_text(question)

        synonyms = species_synonyms(name)
        answer = {
            "id": case_id,
            "answer": name,
            "type": "mineral_species",
            "accepted": synonyms,
            "matchers": [
                {"kind": "keywords_any_word", "values": [name, *synonyms]},
                {"kind": "no_hedge"},
            ],
            "category": rec["crystal_system"].lower() if rec["crystal_system"] else "unknown",
            "difficulty": difficulty_of(rec),
        }
        (expected_dir / case_id).mkdir(parents=True, exist_ok=True)
        json.dump(answer, open(expected_dir / case_id / "answer.json", "w"),
                  ensure_ascii=False, indent=1)

        cases_meta.append({
            "id": case_id,
            "description": f"Identify the mineral from hand-specimen properties ({name}).",
            "tags": [answer["category"], answer["difficulty"]],
        })

    write_traptask_yaml(cases_meta)
    print(f"生成 {len(cases_meta)} 个 case | 候选集 {len(candidates)} 种")
    print(f"难度分布: " + ", ".join(f"{d}={sum(1 for c in cases_meta if d in c['tags'])}"
                                  for d in ["easy", "medium", "hard"]))


def species_synonyms(name: str) -> list[str]:
    """judge 容错用：同义词/变体（与 judge.py 的 SYNONYMS 一致）。"""
    table = {
        "stibnite": ["antimonite"], "labradorite": ["labrador"],
        "nephrite": ["nephritis"], "creedite": ["credit"],
        "cobaltite": ["cobaltin"], "analcime": ["analcim", "analcite"],
        "cancrinite": ["cancrinit"], "elbaite": ["elbait"],
        "scheelite": ["scheelit"], "vesuvianite": ["vesuvian", "idocrase"],
        "titanite": ["sphene"], "fluorite": ["fluorspar"], "barite": ["baryte"],
    }
    return table.get(name, [])


def write_traptask_yaml(cases_meta: list[dict]) -> None:
    lines = ["dirs:", "  inputs: inputs/", "  expected: expected/", "", "cases:"]
    for c in cases_meta:
        lines.append(f"- id: {c['id']}")
        lines.append(f"  description: {json.dumps(c['description'], ensure_ascii=False)}")
        lines.append("  tags:")
        for t in c["tags"]:
            lines.append(f"  - {t}")
    lines += ["judge:", "  cmd: python3 judge.py",
              "grader:", "  cmd: python3 grader.py", ""]
    (TASK_DIR / "traptask.yaml").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
