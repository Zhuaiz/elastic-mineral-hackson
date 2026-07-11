"""作答准确率 vs 检索强度曲线 —— 用 trapstreet 的方式证明 RRF。

思路（用户框架）：固定题集 + 固定 judge，把"喂给模型的检索证据"当变量，
看模型作答准确率随检索增强而上升。曲线爬升即 RRF 的价值证明。

配置（检索强度递增）：
  closed_book  无检索，模型裸答
  bm25         只用野外属性文字做 BM25 → 证据
  image        只用标本照片做图像 kNN → 证据
  rrf_w10/50   RRF 融合(BM25+图像)，检索窗口递增（--configs all 才跑）
  rrf_w100     RRF 融合，rank_window=100 + 硬度过滤（满配）

每格：检索证据拼进 prompt → ES 推理端点作答 → judge.score 判分 → 该配置准确率。
题集读 trapstreet 官方格式（trap/task/inputs/ + expected/）；同时把每配置的
作答写到 trap/solutions/answers/<config>.txt（id|answer），供 submit.py 上传。

作答后端：ES /_inference/completion/<model>（默认 qwen-plus）。ES 在阿里云
VPC 内代理 AI 平台，本机只需 ES basic auth —— 不再依赖 Kibana / 浏览器。

前置: embed_images + index_es 完成；source .env（ES_URL + ES_USER/ES_PASSWORD）
用法: .venv/bin/python trap/eval/accuracy_vs_retrieval.py [--limit N] [--configs all]
输出: 控制台曲线 + trap/eval/results/accuracy_vs_retrieval.json
     + trap/solutions/answers/<config>.txt
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "trap" / "task"))
from config import EMBED_DIR, INDEX_IMAGES  # noqa: E402
from index_es import es_client  # noqa: E402
from judge import score  # noqa: E402

CORPUS_SPLIT = "validation"
CONTEXT_K = 5  # 拼进 prompt 的证据条数
CONFIGS_DEFAULT = ["closed_book", "bm25", "image", "rrf_w100"]
CONFIGS_ALL = ["closed_book", "bm25", "image", "rrf_w10", "rrf_w50", "rrf_w100"]
ANSWER_WORKERS = 4
ANSWER_RETRIES = 3


def load_cases(limit: int | None = None) -> list[dict]:
    """读 trapstreet 官方格式的题集（inputs/<id>/question.txt + expected/<id>/answer.json）。

    检索线索 = 题面第二段（观察属性行），硬度从中解析——全部来自题面，
    不查真值属性表。
    """
    task = ROOT / "trap" / "task"
    cases = []
    for d in sorted((task / "inputs").iterdir()):
        if not d.is_dir():
            continue
        question = (d / "question.txt").read_text()
        expected = json.loads((task / "expected" / d.name / "answer.json").read_text())
        paras = [p.strip() for p in question.split("\n\n") if p.strip()]
        clue = paras[1].rstrip(".")
        m = re.search(r"Mohs hardness (\d+(?:\.\d+)?)", clue)
        cases.append({"id": d.name, "question": question, "expected": expected,
                      "clue": clue, "hardness": float(m.group(1)) if m else None})
    return cases[:limit] if limit else cases


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
    """返回作为上下文的检索命中（含 species + props_text）。closed_book 返回空。

    vector=None（该种无标本图）时 image 腿退化：image 配置返回空，
    rrf 配置只剩 BM25 一路。
    """
    src = ["species", "props_text"]
    if cfg == "closed_book":
        return []
    if cfg == "bm25":
        body = {"size": CONTEXT_K, "_source": src,
                "query": _bm25(clue)["standard"]["query"]}
    elif cfg == "image":
        if vector is None:
            return []
        body = {"size": CONTEXT_K, "_source": src, **_knn(vector, CONTEXT_K)}
    elif cfg.startswith("rrf_w"):
        window = int(cfg.split("_w")[1])
        retrievers = [_bm25(clue)]
        if vector is not None:
            retrievers.append(_knn(vector, window))
        rrf = {"retrievers": retrievers, "rank_window_size": window, "rank_constant": 20}
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


def make_answer_fn(es, model: str):
    """经 ES 推理端点作答（POST /_inference/completion/<model>），带退避重试。"""
    def answer(question: str, context: str) -> str:
        prompt = question if not context else (
            f"{question}\n\nRetrieved reference candidates:\n{context}\n"
            "Answer with the species name only.")
        last_err = None
        for attempt in range(ANSWER_RETRIES):
            try:
                resp = es.perform_request(
                    "POST", f"/_inference/completion/{model}",
                    headers={"accept": "application/json",
                             "content-type": "application/json"},
                    body={"input": prompt})
                return resp["completion"][0]["result"].strip()
            except Exception as e:  # noqa: BLE001 — 网络/限流，重试后仍失败才抛
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{model} 推理连续 {ANSWER_RETRIES} 次失败: {last_err}")

    return answer


def load_image_vectors() -> dict[str, list[float]]:
    """每个种 → 一张 test 切分的代表标本图向量（模拟"地质学家拍的标本照"）。"""
    rows = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    img_by_species: dict[str, list[float]] = {}
    for r in rows:
        if r["split"] == "test":
            img_by_species.setdefault(r["species"], r["vector"])
    return img_by_species


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--configs", default=",".join(CONFIGS_DEFAULT),
                    help=f"逗号分隔或 all；可选 {CONFIGS_ALL}")
    ap.add_argument("--model", default=os.environ.get("INFER_MODEL", "qwen-plus"),
                    help="ES 推理端点名（/_inference/completion/<model>）")
    args = ap.parse_args()
    configs = CONFIGS_ALL if args.configs == "all" else args.configs.split(",")

    es = es_client()
    answer_fn = make_answer_fn(es, args.model)
    cases = load_cases(args.limit)
    img_by_species = load_image_vectors()

    missing = [c["id"] for c in cases if c["expected"]["answer"] not in img_by_species]
    if missing:
        print(f"⚠️ {len(missing)} case 无 test 标本图，image/rrf 腿退化为纯文字: {missing}")

    ans_dir = ROOT / "trap" / "solutions" / "answers"
    ans_dir.mkdir(parents=True, exist_ok=True)

    result = {}
    for cfg in configs:
        def run_case(case: dict) -> tuple[dict, str, dict]:
            vec = img_by_species.get(case["expected"]["answer"])
            ctx = build_context(retrieve(es, cfg, case["clue"], vec, case["hardness"]))
            ans = answer_fn(case["question"], ctx)
            return case, ans, score(case["expected"], ans)

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=ANSWER_WORKERS) as pool:
            rows = list(pool.map(run_case, cases))
        # 压平换行：answers 文件是 id|answer 每行一条，多行作答会破坏格式
        # （judge 对 >8 词的长文一律 0 分，压平不改变判分结果）
        (ans_dir / f"{cfg}.txt").write_text(
            "".join(f"{c['id']}|{' '.join(a.split())}\n" for c, a, _ in rows))
        acc = sum(m["score"] for _, _, m in rows) / len(rows)
        result[cfg] = round(acc, 4)
        bar = "█" * round(acc * 20)
        print(f"{cfg:<12} {acc:>7.1%}  {bar}  "
              f"({time.time() - t0:.0f}s, answers/{cfg}.txt)")

    if {"bm25", "image"} <= result.keys():
        base = max(result["bm25"], result["image"])
        best_rrf = max((v for k, v in result.items() if k.startswith("rrf")), default=0)
        print(f"\nRRF 峰值相对最强单路: {best_rrf - base:+.1%} | "
              f"相对闭卷: {best_rrf - result.get('closed_book', 0):+.1%}")

    out = Path(__file__).resolve().parent / "results"
    out.mkdir(exist_ok=True)
    json.dump({"n_cases": len(cases), "metric": "answer_accuracy_judged",
               "context_k": CONTEXT_K, "answer_model": args.model,
               "accuracy_by_config": result},
              open(out / "accuracy_vs_retrieval.json", "w"), ensure_ascii=False, indent=1)
    print(f"结果已存 {out / 'accuracy_vs_retrieval.json'}")


if __name__ == "__main__":
    main()
