"""为准确率曲线预计算各检索配置的上下文（本地→ES；作答在浏览器里调 Qwen）。

因为 Qwen 平台端点是私网 VPC，笔记本够不着，只有 Kibana 连接器能调。
所以拆两步：本地算好检索证据 → 浏览器读 JSON 循环作答 → 本地判分。

用法: source .env && .venv/bin/python trap/eval/build_contexts.py --limit 40
输出: trap/eval/results/contexts.json  [{id, question, answer, contexts:{config:text}}]
"""
import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "trap" / "task"))
from config import EMBED_DIR  # noqa: E402
from index_es import es_client  # noqa: E402
from make_cases import build_clues  # noqa: E402
from accuracy_vs_retrieval import build_context, retrieve  # noqa: E402

CONFIGS = ["closed_book", "bm25", "image", "rrf_w100"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    es = es_client()
    props = json.load(open(ROOT / "data" / "properties" / "minerals.json"))
    cases = [json.load(open(p)) for p in
             sorted((ROOT / "trap" / "task" / "cases").glob("*.json"))][:args.limit]

    rows = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    img_by_species: dict[str, list[float]] = {}
    for r in rows:
        if r["split"] == "test":
            img_by_species.setdefault(r["species"], r["vector"])

    out = []
    for case in cases:
        truth = case["answer"]
        vector = img_by_species.get(truth)
        if vector is None:
            continue
        rec = props.get(truth, {})
        clue = build_clues(rec) if rec else truth
        contexts = {}
        for cfg in CONFIGS:
            hits = retrieve(es, cfg, clue, vector, rec.get("hardness_min"))
            contexts[cfg] = build_context(hits)
        out.append({"id": case["id"], "question": case["question"],
                    "answer": truth, "contexts": contexts})
        print(f"  {case['id']} {truth}: " +
              ", ".join(f"{c}={len(contexts[c].splitlines())}行" for c in CONFIGS))

    res_dir = Path(__file__).resolve().parent / "results"
    res_dir.mkdir(exist_ok=True)
    json.dump(out, open(res_dir / "contexts.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(out)} 个 case × {len(CONFIGS)} 配置 → {res_dir / 'contexts.json'}")


if __name__ == "__main__":
    main()
