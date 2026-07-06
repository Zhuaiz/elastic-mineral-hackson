"""从 minerals.json 生成 trapstreet 矿物鉴定评测任务的 cases 与参考文档。

每个 case：给出属性描述（不含种名），要求答出矿物种名。
参考文档 = 98 种的完整属性手册（RAG 侧可检索；闭卷侧不可见）。

用法: python3 trapstreet-task/make_cases.py
输出: trapstreet-task/cases/*.json, trapstreet-task/reference.md
注意: 目录布局在注册前需对照 trapstreet 现有任务（如 financebench）的实际格式校准。
"""
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from config import PROPS_DIR  # noqa: E402

TASK_DIR = Path(__file__).resolve().parent
N_CASES = 50
rng = random.Random(42)


def strip_name(text: str, species: str) -> str:
    """把属性文本里的种名脱敏，避免答案泄漏。"""
    pattern = re.compile(re.escape(species), re.IGNORECASE)
    return pattern.sub("this mineral", text)


def main() -> None:
    props = json.load(open(PROPS_DIR / "minerals.json"))
    usable = {k: v for k, v in props.items()
              if v["crystal_system"] and v["hardness_min"] and v["streak"]}
    print(f"可出题的种（结构化字段齐全）: {len(usable)}/{len(props)}")

    species_list = rng.sample(sorted(usable), min(N_CASES, len(usable)))
    cases_dir = TASK_DIR / "cases"
    cases_dir.mkdir(exist_ok=True)
    for i, name in enumerate(species_list):
        rec = usable[name]
        clues = strip_name(rec["props_text"].split(".", 1)[1].strip(), name)
        case = {
            "id": f"mineral-{i:03d}",
            "question": (
                "A field geologist observed a specimen with these properties: "
                f"{clues} Which mineral species is it? "
                "Answer with the species name only."
            ),
            "answer": name,
        }
        json.dump(case, open(cases_dir / f"{case['id']}.json", "w"),
                  ensure_ascii=False, indent=1)

    lines = ["# Mineral Property Handbook (reference)\n"]
    for name, rec in sorted(props.items()):
        lines.append(f"## {name}\n\n{rec['props_text']}\n")
        if rec["wikipedia"]:
            lines.append(rec["wikipedia"] + "\n")
    (TASK_DIR / "reference.md").write_text("\n".join(lines))
    print(f"生成 {len(species_list)} 个 case + reference.md "
          f"({(TASK_DIR / 'reference.md').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
