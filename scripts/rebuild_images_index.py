"""重建 minerals-images：修复分片 ID 冲突吞掉一半语料的 bug（5,498 全量 + 唯一 ID）。

背景: embed_images.py 旧版按"分片内行号"编 ID，两个分片各自从 0 起 →
      validation-00005 在两个分片重复，bulk 覆盖后 5,498 条只剩 2,750 条。
本脚本按 embed_images.iter_rows 的确定顺序对齐 embeddings.parquet（已抽样验证），
重编全局唯一 ID，从源 parquet 补出缺失缩略图，写入 minerals-images-v2，
校验通过后 --cutover 原子切换（删旧索引 + 建同名别名，演示只断 1-2 秒）。

用法:
  .venv/bin/python scripts/rebuild_images_index.py           # 构建 v2 + 校验
  .venv/bin/python scripts/rebuild_images_index.py --cutover # 切换别名
"""
import io
import json
import sys

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

from config import (CLASS_NAMES, EMBED_DIMS, EMBED_DIR, IMAGES_DIR,
                    INDEX_IMAGES, PARQUET_DIR, PROPS_DIR, canonical)
from enrich_es_geo import NEW_FIELDS, enrich_fields
from index_es import IMAGES_MAPPING, es_client, species_fields

INDEX_V2 = "minerals-images-v2"
THUMB_SIZE = 384


def rebuild_rows() -> list[dict]:
    """源 parquet（iter_rows 顺序）与 embeddings.parquet 逐行配对，重编唯一 ID。"""
    emb = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    seq: dict[str, int] = {}
    rows, cursor = [], 0
    for pf in sorted(PARQUET_DIR.glob("*.parquet")):
        split = pf.name.split("-")[0]
        table = pq.read_table(pf)
        for i in range(table.num_rows):
            e = emb[cursor]
            raw = CLASS_NAMES[table["name"][i].as_py()]
            species = canonical(raw)
            assert e["split"] == split and e["species"] == species, \
                f"行 {cursor} 错位: {e['split']}/{e['species']} vs {split}/{species}"
            n = seq[split] = seq.get(split, -1) + 1
            new_id = f"{split}-{n:05d}"
            thumb_path = IMAGES_DIR / species / f"{new_id}.jpg"
            if not thumb_path.exists():
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                img = Image.open(io.BytesIO(table["image"][i]["bytes"].as_py()))
                t = img.convert("RGB")
                t.thumbnail((THUMB_SIZE, THUMB_SIZE))
                t.save(thumb_path, "JPEG", quality=85)
            rows.append({"id": new_id, "class_raw": raw, "species": species,
                         "split": split,
                         "thumb": str(thumb_path.relative_to(IMAGES_DIR.parent.parent)),
                         "vector": e["vector"]})
            cursor += 1
    assert cursor == len(emb), f"行数不齐: {cursor} vs {len(emb)}"
    return rows


def build_v2(es) -> None:
    rows = rebuild_rows()
    print(f"重建 {len(rows)} 行，唯一 ID {len({r['id'] for r in rows})}")

    schema = pa.schema([
        ("id", pa.string()), ("class_raw", pa.string()), ("species", pa.string()),
        ("split", pa.string()), ("thumb", pa.string()),
        ("vector", pa.list_(pa.float32(), EMBED_DIMS)),
    ])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema),
                   EMBED_DIR / "embeddings-v2.parquet")

    props = json.load(open(PROPS_DIR / "minerals.json"))
    mapping = {"properties": {**IMAGES_MAPPING["properties"],
                              **NEW_FIELDS["properties"]}}
    if es.indices.exists(index=INDEX_V2):
        es.indices.delete(index=INDEX_V2)
    es.indices.create(index=INDEX_V2, mappings=mapping)

    def gen():
        for r in rows:
            rec = props.get(r["species"])
            base = species_fields(rec) if rec else {"species": r["species"],
                                                    "props_text": r["species"]}
            extra = enrich_fields(rec) if rec else {}
            yield {"_index": INDEX_V2, "_id": r["id"], **base, **extra,
                   "class_raw": r["class_raw"], "split": r["split"],
                   "thumb": r["thumb"], "image_vector": r["vector"]}

    from elasticsearch import helpers
    ok, errors = helpers.bulk(es, gen(), chunk_size=100, raise_on_error=False)
    es.indices.refresh(index=INDEX_V2)
    print(f"{INDEX_V2}: 写入 {ok}，错误 {len(errors) if errors else 0}")

    total = es.count(index=INDEX_V2)["count"]
    vec = es.count(index=INDEX_V2,
                   query={"exists": {"field": "image_vector"}})["count"]
    sp = es.search(index=INDEX_V2, size=0,
                   aggs={"n": {"cardinality": {"field": "species"}}})
    probe = es.search(index=INDEX_V2, size=1,
                      query={"term": {"species": "malachite"}},
                      _source=["image_vector"])["hits"]["hits"][0]
    knn = es.search(index=INDEX_V2, size=5, _source=["species"], knn={
        "field": "image_vector", "k": 5, "num_candidates": 50,
        "query_vector": probe["_source"]["image_vector"]})
    top = [h["_source"]["species"] for h in knn["hits"]["hits"]]
    print(f"校验: docs {total}/5498 | 向量 {vec} | 种数 "
          f"{sp['aggregations']['n']['value']}/98 | malachite 自检索近邻 {top}")
    if total != 5498 or vec != 5498:
        sys.exit("校验未通过，不要 cutover")
    print("校验通过。执行 --cutover 切换。")


def cutover(es) -> None:
    total = es.count(index=INDEX_V2)["count"]
    if total != 5498:
        sys.exit(f"{INDEX_V2} 只有 {total} 条，拒绝切换")
    if es.indices.exists_alias(name=INDEX_IMAGES):
        old = list(es.indices.get_alias(name=INDEX_IMAGES))
        actions = [{"remove": {"index": i, "alias": INDEX_IMAGES}} for i in old]
        actions.append({"add": {"index": INDEX_V2, "alias": INDEX_IMAGES}})
        es.indices.update_aliases(actions=actions)
        print(f"别名原子切换 {old} -> {INDEX_V2}")
    else:
        es.indices.delete(index=INDEX_IMAGES)
        es.indices.put_alias(index=INDEX_V2, name=INDEX_IMAGES)
        print(f"旧索引已删，别名 {INDEX_IMAGES} -> {INDEX_V2}")
    print("完成:", es.count(index=INDEX_IMAGES)["count"], "docs 经别名可查")


if __name__ == "__main__":
    client = es_client()
    if "--cutover" in sys.argv:
        cutover(client)
    else:
        build_v2(client)
