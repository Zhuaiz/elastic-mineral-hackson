"""检索与作答的共享原语——eval 曲线与 tp solution 用同一套查询保证可比。

依赖刻意保持最小（elasticsearch 客户端即可，不引 pyarrow/torch），
solve.py 在 tp 的 per-case 子进程里 import 本模块要够快。
"""
import re
import time

CORPUS_SPLIT = "validation"
CONTEXT_K = 5  # 拼进 prompt 的证据条数
INDEX_IMAGES = "minerals-images"
ANSWER_RETRIES = 3
CONFIGS_DEFAULT = ["closed_book", "bm25", "image", "rrf_w100"]
CONFIGS_ALL = ["closed_book", "bm25", "image", "rrf_w10", "rrf_w50", "rrf_w100"]


def parse_clue(question: str) -> tuple[str, float | None]:
    """题面 → (观察属性行, 硬度下限)。全部来自题面，不查真值属性表。"""
    paras = [p.strip() for p in question.split("\n\n") if p.strip()]
    clue = paras[1].rstrip(".") if len(paras) > 1 else question.strip()
    m = re.search(r"Mohs hardness (\d+(?:\.\d+)?)", clue)
    return clue, float(m.group(1)) if m else None


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


def make_answer_fn(es, model: str, temperature: float | None = None):
    """经 ES 推理端点作答（POST /_inference/completion/<model>），带退避重试。

    temperature=0 尽量贪心解码以利复现；None 用端点默认（榜上首批 run 即默认）。
    """
    def answer(question: str, context: str) -> str:
        prompt = question if not context else (
            f"{question}\n\nRetrieved reference candidates:\n{context}\n"
            "Answer with the species name only.")
        body = {"input": prompt}
        if temperature is not None:
            body["task_settings"] = {"temperature": temperature}
        last_err = None
        for attempt in range(ANSWER_RETRIES):
            try:
                resp = es.perform_request(
                    "POST", f"/_inference/completion/{model}",
                    headers={"accept": "application/json",
                             "content-type": "application/json"},
                    body=body)
                return resp["completion"][0]["result"].strip()
            except Exception as e:  # noqa: BLE001 — 网络/限流，重试后仍失败才抛
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{model} 推理连续 {ANSWER_RETRIES} 次失败: {last_err}")

    return answer
