"""RRF 融合检索 CLI：BM25(属性文本) + kNN(jina-clip-v2 向量) + 结构化过滤，一个 retriever 完成。

用法:
  .venv/bin/python scripts/search_cli.py --text "green mineral with green streak, hardness about 4"
  .venv/bin/python scripts/search_cli.py --text "绿色 条痕绿色 硬度4"          # 中文走向量腿
  .venv/bin/python scripts/search_cli.py --image path/to/photo.jpg
  .venv/bin/python scripts/search_cli.py --text "..." --crystal-system Hexagonal --hardness 6.5
"""
import argparse
import json

from index_es import es_client
from config import EMBED_MODEL, INDEX_IMAGES


def embed_query(text: str | None, image: str | None) -> list[float]:
    from embedder import encode_images, encode_texts
    if image:
        from PIL import Image
        return encode_images([Image.open(image).convert("RGB")])[0].tolist()
    return encode_texts([text])[0].tolist()


def build_query(vector: list[float], text: str | None,
                crystal_system: str | None, hardness: float | None) -> dict:
    retrievers = [
        {"knn": {"field": "image_vector", "query_vector": vector,
                 "k": 20, "num_candidates": 100}},
    ]
    if text:
        retrievers.insert(0, {"standard": {"query": {"multi_match": {
            "query": text,
            "fields": ["name^2", "props_text", "description"]}}}})
    rrf: dict = {"retrievers": retrievers, "rank_window_size": 50, "rank_constant": 20}
    filters = []
    if crystal_system:
        filters.append({"term": {"crystal_system": crystal_system}})
    if hardness is not None:
        filters.append({"range": {"hardness_min": {"lte": hardness}}})
        filters.append({"range": {"hardness_max": {"gte": hardness}}})
    if filters:
        rrf["filter"] = filters
    return {"retriever": {"rrf": rrf}, "size": 10,
            "_source": ["species", "props_text", "thumb", "crystal_system",
                        "hardness_min", "hardness_max"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--image")
    ap.add_argument("--crystal-system")
    ap.add_argument("--hardness", type=float)
    ap.add_argument("--show-query", action="store_true")
    args = ap.parse_args()
    if not args.text and not args.image:
        ap.error("需要 --text 或 --image")

    vector = embed_query(args.text, args.image)
    body = build_query(vector, args.text, args.crystal_system, args.hardness)
    if args.show_query:
        redacted = json.loads(json.dumps(body))
        redacted["retriever"]["rrf"]["retrievers"][-1]["knn"]["query_vector"] = "[...1024 dims...]"
        print(json.dumps(redacted, ensure_ascii=False, indent=1))

    res = es_client().search(index=INDEX_IMAGES, **body)
    species_votes: dict[str, int] = {}
    print(f"\ntop {len(res['hits']['hits'])} hits:")
    for h in res["hits"]["hits"]:
        s = h["_source"]
        species_votes[s["species"]] = species_votes.get(s["species"], 0) + 1
        print(f"  {h['_score']:.4f}  {s['species']:16s} "
              f"[{s.get('crystal_system','?')}, H {s.get('hardness_min')}-{s.get('hardness_max')}]  "
              f"{s.get('thumb','')}")
    best = max(species_votes, key=species_votes.get)
    print(f"\n判定（top-10 多数票）: {best}  votes={species_votes[best]}")


if __name__ == "__main__":
    main()
