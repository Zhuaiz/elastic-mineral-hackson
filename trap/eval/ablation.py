"""RRF 消融实验：证明"融合 > 任一单路"。这是本项目对 RRF 作用性的技术证据。

对比三种检索策略在矿物鉴定上的 top-1 / top-3 准确率：
  A. 图像 kNN 单路   （只看照片，jina-clip-v2 向量）
  B. BM25 文本单路   （只看野外观察到的属性文字）
  C. RRF 融合        （图像 + 文本 + 硬度过滤，一个 retriever）

评测协议（防泄漏）:
  查询集 = test 切分的标本；检索语料 = index 中 split=validation 的标本。
  即"拿没见过的标本，去已知标本库里检索最相似者，投票定种"。

前置: 已跑完 embed_images + index_es；export ES_URL / ES_API_KEY
用法: .venv/bin/python trap/eval/ablation.py [--limit 300]
输出: 控制台消融表 + trap/eval/results/ablation.json
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "trap" / "task"))
from config import EMBED_DIR, INDEX_IMAGES  # noqa: E402
from index_es import es_client  # noqa: E402
from make_cases import build_clues  # noqa: E402

CORPUS_SPLIT = "validation"
TOPK = 10


def majority_species(hits: list) -> tuple[str | None, list[str]]:
    """top-k 命中里按种名多数票，返回 (top1, 去重排序的候选前3)。"""
    species = [h["_source"]["species"] for h in hits]
    if not species:
        return None, []
    ranked = [s for s, _ in Counter(species).most_common()]
    return ranked[0], ranked[:3]


def knn_leg(vector: list[float]) -> dict:
    return {"knn": {"field": "image_vector", "query_vector": vector,
                    "k": TOPK, "num_candidates": 100,
                    "filter": {"term": {"split": CORPUS_SPLIT}}}}


def bm25_leg(clue: str) -> dict:
    return {"standard": {"query": {"bool": {
        "must": {"multi_match": {"query": clue,
                                 "fields": ["props_text", "description", "name^2"]}},
        "filter": {"term": {"split": CORPUS_SPLIT}}}}}}


def search_image_only(es, vector, clue, props):
    body = {"size": TOPK, "_source": ["species"], **knn_leg(vector)}
    return es.search(index=INDEX_IMAGES, **body)["hits"]["hits"]


def search_text_only(es, vector, clue, props):
    body = {"size": TOPK, "_source": ["species"],
            "query": bm25_leg(clue)["standard"]["query"]}
    return es.search(index=INDEX_IMAGES, **body)["hits"]["hits"]


def search_rrf(es, vector, clue, props):
    hardness = props.get("hardness_min")
    rrf = {"retrievers": [bm25_leg(clue), knn_leg(vector)],
           "rank_window_size": 50, "rank_constant": 20}
    if hardness:
        rrf["filter"] = [{"term": {"split": CORPUS_SPLIT}},
                         {"range": {"hardness_min": {"lte": hardness}}},
                         {"range": {"hardness_max": {"gte": hardness}}}]
    body = {"size": TOPK, "_source": ["species"], "retriever": {"rrf": rrf}}
    return es.search(index=INDEX_IMAGES, **body)["hits"]["hits"]


STRATEGIES = {"image_only": search_image_only,
              "text_only": search_text_only,
              "rrf_fusion": search_rrf}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    es = es_client()
    props_all = json.load(open(ROOT / "data" / "properties" / "minerals.json"))
    rows = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    queries = [r for r in rows if r["split"] == "test"]
    if args.limit:
        queries = queries[:args.limit]
    print(f"查询标本(test): {len(queries)} | 语料(index 内 split={CORPUS_SPLIT})")

    scores = {k: {"top1": 0, "top3": 0} for k in STRATEGIES}
    for i, q in enumerate(queries):
        truth = q["species"]
        rec = props_all.get(truth, {})
        clue = build_clues(rec) if rec else truth
        for name, fn in STRATEGIES.items():
            top1, top3 = majority_species(fn(es, q["vector"], clue, rec))
            scores[name]["top1"] += int(top1 == truth)
            scores[name]["top3"] += int(truth in top3)
        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(queries)}")

    n = len(queries)
    print("\n" + "=" * 52)
    print(f"{'策略':<16}{'top-1':>12}{'top-3':>12}")
    print("-" * 52)
    result = {}
    for name in STRATEGIES:
        t1 = scores[name]["top1"] / n
        t3 = scores[name]["top3"] / n
        result[name] = {"top1": round(t1, 4), "top3": round(t3, 4)}
        print(f"{name:<16}{t1:>11.1%}{t3:>12.1%}")
    print("=" * 52)
    lift = result["rrf_fusion"]["top1"] - max(result["image_only"]["top1"],
                                              result["text_only"]["top1"])
    print(f"RRF 相对最强单路的 top-1 提升: {lift:+.1%}")

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    json.dump({"n_queries": n, "corpus_split": CORPUS_SPLIT, "topk": TOPK,
               "scores": result, "rrf_top1_lift_over_best_single": round(lift, 4)},
              open(out_dir / "ablation.json", "w"), ensure_ascii=False, indent=1)
    print(f"结果已存 {out_dir / 'ablation.json'}")


if __name__ == "__main__":
    main()
