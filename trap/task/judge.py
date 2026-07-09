"""trapstreet 矿物鉴定任务判分器：种名归一化后精确匹配。

用法: python3 judge.py <case.json> <answer.txt>   -> 输出 1 (对) / 0 (错)
"""
import json
import re
import sys

# 同义词/变体 -> 规范名（判分容错，双向收敛到同一规范名）
SYNONYMS = {
    "stibnite": "stibnite", "antimonite": "stibnite",
    "labradorite": "labradorite", "labrador": "labradorite",
    "nephrite": "nephrite", "nephritis": "nephrite",
    "creedite": "creedite", "credit": "creedite",
    "cobaltite": "cobaltite", "cobaltin": "cobaltite",
    "analcime": "analcime", "analcim": "analcime", "analcite": "analcime",
    "cancrinite": "cancrinite", "cancrinit": "cancrinite",
    "elbaite": "elbaite", "elbait": "elbaite",
    "scheelite": "scheelite", "scheelit": "scheelite",
    "vesuvianite": "vesuvianite", "vesuvian": "vesuvianite", "idocrase": "vesuvianite",
    "titanite": "titanite", "sphene": "titanite",
    "fluorite": "fluorite", "fluorspar": "fluorite",
    "barite": "barite", "baryte": "barite",
}


def normalize(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z一-鿿 ]", "", s)
    s = s.split("\n")[0].strip()
    return SYNONYMS.get(s, s)


def judge(expected: str, actual: str) -> int:
    return int(normalize(expected) == normalize(actual))


if __name__ == "__main__":
    case = json.load(open(sys.argv[1]))
    answer = open(sys.argv[2]).read()
    print(judge(case["answer"], answer))
