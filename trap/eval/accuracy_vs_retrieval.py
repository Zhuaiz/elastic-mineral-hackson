"""作答准确率 vs 检索强度曲线 —— 用 trapstreet 的方式证明 RRF。

思路（用户框架）：固定题集 + 固定 judge，把"喂给模型的检索证据"当变量，
看模型作答准确率随检索增强而上升。曲线爬升即 RRF 的价值证明。

配置（检索强度递增）：
  closed_book  无检索，模型裸答
  bm25         只用野外属性文字做 BM25 → 证据
  image        只用标本照片做图像 kNN → 证据
  rrf_w10      RRF 融合(BM25+图像)，rank_window=10
  rrf_w50      RRF 融合，rank_window=50
  rrf_w100     RRF 融合，rank_window=100（+硬度过滤）

每格：检索证据拼进 prompt → answer_fn 作答 → judge.py 判分 → 该配置准确率。
预期：准确率随强度上升，在 RRF 处最高、并趋于平台。

前置：embed_images + index_es 完成；export ES_URL/ES_API_KEY；
     作答后端二选一：Agent Builder converse（KIBANA_URL）或自定义 answer_fn。
用法: .venv/bin/python trap/eval/accuracy_vs_retrieval.py [--limit 50]
输出: 控制台曲线 + trap/eval/results/accuracy_vs_retrieval.json
"""
import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "trap" / "task"))
from config import EMBED_DIR, INDEX_IMAGES  # noqa: E402
from index_es import es_client  # noqa: E402
from judge import judge  # noqa: E402
from make_cases import build_clues  # noqa: E402

CORPUS_SPLIT = "validation"
CONTEXT_K = 5  # 拼进 prompt 的证据条数


def _bm25(clue: str) -> dict:
    return {"standard": {"query": {"bool": {
        "must": {"multi_match": {"query": clue,
                                 "fields": ["props_text", "description", "name^2"]}},
        "filter": {"term": {"split": CORPUS_SPLIT}}}}}}


def _knn(vector: list[float], k: int) -> dict:
    return {"knn": {"field": "image_vector", "query_vector": vector,
                    "k": k, "num_candidates": max(100, k * 4),
                    "filter": {"term": {"split": CORPUS_SPLIT}}}}


def retrieve(es, cfg: str, clue: str, vector, hardness) -> list[dict]:
    """返回作为上下文的检索命中（含 species + props_text）。closed_book 返回空。"""
    src = ["species", "props_text"]
    if cfg == "closed_book":
        return []
    if cfg == "bm25":
        body = {"size": CONTEXT_K, "_source": src,
                "query": _bm25(clue)["standard"]["query"]}
    elif cfg == "image":
        body = {"size": CONTEXT_K, "_source": src, **_knn(vector, CONTEXT_K)}
    elif cfg.startswith("rrf_w"):
        window = int(cfg.split("_w")[1])
        rrf = {"retrievers": [_bm25(clue), _knn(vector, window)],
               "rank_window_size": window, "rank_constant": 20}
        if window >= 100 and hardness:
            rrf["filter"] = [{"term": {"split": CORPUS_SPLIT}},
                             {"range": {"hardness_min": {"lte": hardness}}},
                             {"range": {"hardness_max": {"gte": hardness}}}]
        body = {"size": CONTEXT_K, "_source": src, "retriever": {"rrf": rrf}}
    else:
        raise ValueError(cfg)
    return es.search(index=INDEX_IMAGES, **body)["hits"]["hits"]


def build_context(hits: list[dict]) -> str:
    seen, lines = set(), []
    for h in hits:
        s = h["_source"]
        if s["species"] in seen:
            continue
        seen.add(s["species"])
        lines.append(f"- {s['species']}: {s.get('props_text', '')}")
    return "\n".join(lines)


def make_answer_fn():
    """作答后端：优先 Agent Builder converse；缺配置则给出接线指引。"""
    import os
    kibana, key = os.environ.get("KIBANA_URL"), os.environ.get("ES_API_KEY")
    if not (kibana and key):
        raise SystemExit(
            "需要作答后端。二选一:\n"
            "  A) export KIBANA_URL=... ES_API_KEY=...（走 Agent Builder converse）\n"
            "  B) 在本文件 make_answer_fn 里替换为你的模型调用（trapstreet 用的同一模型）")
    import urllib.request

    def answer(question: str, context: str) -> str:
        prompt = question if not context else (
            f"{question}\n\nRetrieved reference candidates:\n{context}\n"
            "Answer with the species name only.")
        req = urllib.request.Request(
            f"{kibana.rstrip('/')}/api/agent_builder/converse",
            data=json.dumps({"agent_id": "mineralogist", "input": prompt}).encode(),
            headers={"Content-Type": "application/json", "kbn-xsrf": "true",
                     "Authorization": f"ApiKey {key}"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        return resp.get("response") or resp.get("output") or json.dumps(resp)[:80]

    return answer


CONFIGS = ["closed_book", "bm25", "image", "rrf_w10", "rrf_w50", "rrf_w100"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    es = es_client()
    answer_fn = make_answer_fn()
    props = json.load(open(ROOT / "data" / "properties" / "minerals.json"))
    cases = [json.load(open(p)) for p in
             sorted((ROOT / "trap" / "task" / "cases").glob("*.json"))]
    if args.limit:
        cases = cases[:args.limit]

    # 每个 case 的答案种名 → 一张 test 切分的代表标本图向量
    rows = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    img_by_species: dict[str, list[float]] = {}
    for r in rows:
        if r["split"] == "test":
            img_by_species.setdefault(r["species"], r["vector"])

    hits = {c: 0 for c in CONFIGS}
    n = 0
    for case in cases:
        truth = case["answer"]
        vector = img_by_species.get(truth)
        if vector is None:  # 无对应标本图则跳过（保证 image/rrf 腿可用）
            continue
        n += 1
        rec = props.get(truth, {})
        clue = build_clues(rec) if rec else truth
        for cfg in CONFIGS:
            ctx = build_context(retrieve(es, cfg, clue, vector, rec.get("hardness_min")))
            hits[cfg] += judge(truth, answer_fn(case["question"], ctx))
        if n % 10 == 0:
            print(f"  ...{n} cases")

    print("\n" + "=" * 46)
    print(f"{'检索配置':<14}{'作答准确率':>16}")
    print("-" * 46)
    result = {}
    for cfg in CONFIGS:
        acc = hits[cfg] / n if n else 0.0
        result[cfg] = round(acc, 4)
        bar = "█" * round(acc * 20)
        print(f"{cfg:<14}{acc:>9.1%}  {bar}")
    print("=" * 46)
    base = max(result["bm25"], result["image"])
    best_rrf = max(result["rrf_w10"], result["rrf_w50"], result["rrf_w100"])
    print(f"RRF 峰值相对最强单路: {best_rrf - base:+.1%} | "
          f"相对闭卷: {best_rrf - result['closed_book']:+.1%}")

    out = Path(__file__).resolve().parent / "results"
    out.mkdir(exist_ok=True)
    json.dump({"n_cases": n, "metric": "answer_accuracy_judged",
               "context_k": CONTEXT_K, "accuracy_by_config": result},
              open(out / "accuracy_vs_retrieval.json", "w"), ensure_ascii=False, indent=1)
    print(f"结果已存 {out / 'accuracy_vs_retrieval.json'}")


if __name__ == "__main__":
    main()
