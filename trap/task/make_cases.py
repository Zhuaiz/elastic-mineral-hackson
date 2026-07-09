"""生成 trapstreet 矿物鉴定任务（闭卷 vs RAG 头条对比）。

设计要点（见 ../README.md 的两层评测哲学）：
- 题面 = 野外可观察属性（晶系/硬度/条痕/颜色/光泽/透明度），**不含化学式**
  —— 化学式等于送答案，会抹平闭卷 vs RAG 的差值。
- 属性值是事实（硬度 7、白条痕），不受版权限制，可公开。
- 参考文档 reference.md 仅用 Wikipedia 摘要（CC-BY-SA，已署名），避开 Mindat（不可再分发）。

用法: python3 trap/task/make_cases.py
输出: trap/task/cases/*.json, trap/task/reference.md, trap/task/task.json
"""
import json
import random
import re
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
ROOT = TASK_DIR.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from config import PROPS_DIR  # noqa: E402

N_CASES = 50
rng = random.Random(42)


def short(value: str, words: int = 6) -> str:
    """取前若干词的事实性描述，避免搬运长句表达。"""
    if not value:
        return ""
    tokens = re.split(r"[,.;]", value)[0].split()
    return " ".join(tokens[:words]).strip()


def build_clues(rec: dict) -> str:
    """只用可观察的事实属性，绝不含化学式。"""
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


def main() -> None:
    props = json.load(open(PROPS_DIR / "minerals.json"))
    # 出题只选可观察字段齐全的种（保证题目可答）
    usable = {k: v for k, v in props.items()
              if v["crystal_system"] and v["hardness_min"] and v["streak"] and v["color"]}
    print(f"可出题的种（可观察字段齐全）: {len(usable)}/{len(props)}")

    species_list = rng.sample(sorted(usable), min(N_CASES, len(usable)))
    cases_dir = TASK_DIR / "cases"
    cases_dir.mkdir(exist_ok=True)
    for f in cases_dir.glob("*.json"):
        f.unlink()
    for i, name in enumerate(species_list):
        clues = build_clues(usable[name])
        case = {
            "id": f"mineral-{i:03d}",
            "question": (
                "A field geologist recorded these hand-specimen observations: "
                f"{clues}. Identify the single most likely mineral species. "
                "Answer with the species name only (one word, lowercase)."
            ),
            "answer": name,
        }
        json.dump(case, open(cases_dir / f"{case['id']}.json", "w"),
                  ensure_ascii=False, indent=1)

    # 参考文档：仅 Wikipedia 摘要（CC-BY-SA 4.0，署名）+ 事实属性，公开安全
    lines = [
        "# Mineral Identification Reference\n",
        "> Descriptions below are excerpts from English Wikipedia "
        "(CC BY-SA 4.0). Physical-property facts (Mohs hardness, streak, "
        "crystal system) are objective measurements compiled from public "
        "mineralogical sources.\n",
    ]
    for name in sorted(props):
        rec = props[name]
        facts = build_clues(rec)
        lines.append(f"## {name}\n")
        if facts:
            lines.append(f"**Observable properties:** {facts}.\n")
        if rec["wikipedia"]:
            lines.append(rec["wikipedia"] + "\n")
    (TASK_DIR / "reference.md").write_text("\n".join(lines))

    task_meta = {
        "id": "mineral-id",
        "name": "Mineral Identification from Field Observations",
        "description": (
            "Given hand-specimen observations (crystal system, Mohs hardness, "
            "streak, color, luster) of one of 98 mineral species, name the "
            "species. Tests closed-book recall vs retrieval over a mineral "
            "catalog. Reference: Wikipedia (CC BY-SA 4.0)."
        ),
        "judge": "judge.py",
        "reference": "reference.md",
        "cases_dir": "cases",
        "num_cases": len(species_list),
    }
    json.dump(task_meta, open(TASK_DIR / "task.json", "w"),
              ensure_ascii=False, indent=1)

    ref_kb = (TASK_DIR / "reference.md").stat().st_size // 1024
    print(f"生成 {len(species_list)} 个 case + reference.md ({ref_kb} KB) + task.json")
    sample = json.load(open(cases_dir / "mineral-000.json"))
    leaked = sample["answer"] in sample["question"].lower()
    print(f"答案泄漏检查: {'⚠️ 泄漏' if leaked else '✓ 未泄漏'}")
    print(f"示例题面: {sample['question'][:170]}")


if __name__ == "__main__":
    main()
