"""为准确率曲线预计算各检索配置的上下文（浏览器兜底路径，一般用不到）。

正常路径是 accuracy_vs_retrieval.py 端到端本地跑（ES 推理端点作答）。
本脚本仅在 ES 推理端点不可用、只能靠浏览器里的 Kibana 连接器作答时用：
本地算好检索证据 → 浏览器读 JSON 循环作答 → 本地判分。

用法: source .env && .venv/bin/python trap/eval/build_contexts.py --limit 40
输出: trap/eval/results/contexts.json  [{id, question, answer, contexts:{config:text}}]
"""
import argparse
import json
from pathlib import Path

from accuracy_vs_retrieval import (CONFIGS_DEFAULT, build_context, load_cases,
                                   load_image_vectors, retrieve)

import sys  # noqa: E402  (path 注入已由 accuracy_vs_retrieval 完成)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from index_es import es_client  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    es = es_client()
    cases = load_cases(args.limit)
    img_by_species = load_image_vectors()

    out = []
    for case in cases:
        truth = case["expected"]["answer"]
        vector = img_by_species.get(truth)
        contexts = {}
        for cfg in CONFIGS_DEFAULT:
            hits = retrieve(es, cfg, case["clue"], vector, case["hardness"])
            contexts[cfg] = build_context(hits)
        out.append({"id": case["id"], "question": case["question"],
                    "answer": truth, "contexts": contexts})
        print(f"  {case['id']} {truth}: " +
              ", ".join(f"{c}={len(contexts[c].splitlines())}行" for c in CONFIGS_DEFAULT))

    res_dir = Path(__file__).resolve().parent / "results"
    res_dir.mkdir(exist_ok=True)
    json.dump(out, open(res_dir / "contexts.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(out)} 个 case × {len(CONFIGS_DEFAULT)} 配置 → {res_dir / 'contexts.json'}")


if __name__ == "__main__":
    main()
