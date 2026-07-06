"""创建 ES 索引并批量写入：图片索引（向量+反规范化属性）+ 种属索引（Agent 的 ES|QL 工具用）。

前置: export ES_URL=https://xxx.es.region.cloud.es.io:443  ES_API_KEY=xxx
用法: .venv/bin/python scripts/index_es.py
"""
import json

import pyarrow.parquet as pq
from elasticsearch import Elasticsearch, helpers

from config import (EMBED_DIMS, EMBED_DIR, ES_API_KEY, ES_URL,
                    INDEX_IMAGES, INDEX_SPECIES, PROPS_DIR)

IMAGES_MAPPING = {
    "properties": {
        "species": {"type": "keyword"},
        "class_raw": {"type": "keyword"},
        "split": {"type": "keyword"},
        "name": {"type": "text"},
        "props_text": {"type": "text"},
        "description": {"type": "text"},
        "formula": {"type": "keyword"},
        "crystal_system": {"type": "keyword"},
        "streak": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "color": {"type": "text"},
        "luster": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "hardness_min": {"type": "float"},
        "hardness_max": {"type": "float"},
        "density": {"type": "float"},
        "image_vector": {"type": "dense_vector", "dims": EMBED_DIMS,
                         "index": True, "similarity": "cosine"},
        "thumb": {"type": "keyword", "index": False},
    }
}

SPECIES_MAPPING = {
    "properties": {
        "species": {"type": "keyword"},
        "name": {"type": "text"},
        "props_text": {"type": "text"},
        "description": {"type": "text"},
        "formula": {"type": "keyword"},
        "crystal_system": {"type": "keyword"},
        "streak": {"type": "keyword"},
        "color": {"type": "text"},
        "luster": {"type": "keyword"},
        "hardness_min": {"type": "float"},
        "hardness_max": {"type": "float"},
        "density": {"type": "float"},
    }
}


def es_client() -> Elasticsearch:
    if not ES_URL or not ES_API_KEY:
        raise SystemExit("先设置 ES_URL 与 ES_API_KEY 环境变量（Elastic Cloud 部署页生成）")
    return Elasticsearch(ES_URL, api_key=ES_API_KEY, request_timeout=120)


def species_fields(rec: dict) -> dict:
    return {
        "species": rec["species"], "name": rec["species"],
        "props_text": rec["props_text"], "description": rec["wikipedia"],
        "formula": rec["formula"], "crystal_system": rec["crystal_system"],
        "streak": rec["streak"], "color": rec["color"], "luster": rec["luster"],
        "hardness_min": rec["hardness_min"], "hardness_max": rec["hardness_max"],
        "density": rec["density"],
    }


def main() -> None:
    es = es_client()
    props = json.load(open(PROPS_DIR / "minerals.json"))
    print(f"cluster: {es.info()['version']['number']}, license: "
          f"{es.license.get()['license']['type']}")

    for index, mapping in [(INDEX_IMAGES, IMAGES_MAPPING), (INDEX_SPECIES, SPECIES_MAPPING)]:
        if es.indices.exists(index=index):
            es.indices.delete(index=index)
        es.indices.create(index=index, mappings=mapping)
        print(f"created {index}")

    ok, _ = helpers.bulk(es, (
        {"_index": INDEX_SPECIES, "_id": rec["species"], **species_fields(rec)}
        for rec in props.values()
    ))
    print(f"{INDEX_SPECIES}: {ok} docs")

    table = pq.read_table(EMBED_DIR / "embeddings.parquet")
    rows = table.to_pylist()

    def gen():
        for r in rows:
            rec = props.get(r["species"])
            base = species_fields(rec) if rec else {"species": r["species"], "props_text": r["species"]}
            yield {"_index": INDEX_IMAGES, "_id": r["id"], **base,
                   "class_raw": r["class_raw"], "split": r["split"],
                   "thumb": r["thumb"], "image_vector": r["vector"]}

    ok, _ = helpers.bulk(es, gen(), chunk_size=200)
    es.indices.refresh(index=INDEX_IMAGES)
    print(f"{INDEX_IMAGES}: {ok} docs")


if __name__ == "__main__":
    main()
