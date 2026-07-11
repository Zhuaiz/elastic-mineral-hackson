"""为 trapstreet 提交构建两个 solution 的检索上下文（本地→ES）。

两个 solution：
  closed_book  — 无检索，Qwen 从 98 候选里裸猜
  elastic_rag  — jina-clip-v2 把属性文字编码 → RRF(BM25 props_text + 跨模态图像kNN
                 + 硬度过滤) 检索矿物库 → 候选证据喂给 Qwen

Qwen 作答在浏览器里经 Kibana 连接器跑（私网端点笔记本够不着），本脚本只出上下文。

用法: source .env && .venv/bin/python trap/solutions/build_solution.py
输出: trap/solutions/contexts_all.json  [{id, question, answer, closed_book, elastic_rag}]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from config import INDEX_IMAGES  # noqa: E402
from index_es import es_client  # noqa: E402

TASK = ROOT / "trap" / "task"
CORPUS_SPLIT = "validation"
TOPK = 6


def rrf_context(es, query_text: str, vector: list[float], hardness) -> str:
    bm25 = {"standard": {"query": {"bool": {
        "must": {"multi_match": {"query": query_text,
                                 "fields": ["props_text", "description", "name^2"]}},
        "filter": {"term": {"split": CORPUS_SPLIT}}}}}}
    knn = {"knn": {"field": "image_vector", "query_vector": vector,
                   "k": 30, "num_candidates": 200,
                   "filter": {"term": {"split": CORPUS_SPLIT}}}}
    rrf = {"retrievers": [bm25, knn], "rank_window_size": 50, "rank_constant": 20}
    if hardness:
        rrf["filter"] = [{"term": {"split": CORPUS_SPLIT}},
                         {"range": {"hardness_min": {"lte": hardness}}},
                         {"range": {"hardness_max": {"gte": hardness}}}]
    hits = es.search(index=INDEX_IMAGES, size=TOPK, _source=["species", "props_text"],
                     retriever={"rrf": rrf})["hits"]["hits"]
    seen, lines = set(), []
    for h in hits:
        s = h["_source"]
        if s["species"] in seen:
            continue
        seen.add(s["species"])
        lines.append(f"- {s['species']}: {s.get('props_text','')[:180]}")
    return "\n".join(lines)


def main() -> None:
    from embedder import encode_texts
    es = es_client()
    props = json.load(open(ROOT / "data" / "properties" / "minerals.json"))

    out = []
    case_ids = sorted(p.name for p in (TASK / "inputs").iterdir() if p.is_dir())
    for cid in case_ids:
        question = (TASK / "inputs" / cid / "question.txt").read_text()
        expected = json.load(open(TASK / "expected" / cid / "answer.json"))
        species = expected["answer"]
        rec = props.get(species, {})
        # 检索查询 = 题面里的属性行（第一段观察），不含候选清单
        m = re.search(r"unknown mineral:\s*\n\s*(.+?)\.\s*\n", question, re.S)
        clue = (m.group(1).strip() if m else species)
        vec = encode_texts([clue])[0].tolist()
        out.append({
            "id": cid, "question": question, "answer": species,
            "closed_book": "",
            "elastic_rag": rrf_context(es, clue, vec, rec.get("hardness_min")),
        })
        print(f"  {cid}: rag={len(out[-1]['elastic_rag'].splitlines())}候选")

    res = Path(__file__).resolve().parent / "contexts_all.json"
    json.dump(out, open(res, "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(out)} case → {res}")


if __name__ == "__main__":
    main()
