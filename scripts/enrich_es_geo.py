"""给线上索引补充 Maps/Graph 字段（只增不改，不动向量与 props_text，演示零影响）。

新增字段: elements(keyword[]) / type_locality(geo_point) /
          type_locality_name / type_locality_country (keyword)
- minerals-species: 98 条 doc 局部更新（_id=species）
- minerals-images: 单次 _update_by_query，painless 按 species 查表写入

前置: source .env
用法: .venv/bin/python scripts/enrich_es_geo.py
"""
import json

from config import INDEX_IMAGES, INDEX_SPECIES, PROPS_DIR
from index_es import es_client

NEW_FIELDS = {
    "properties": {
        "elements": {"type": "keyword"},
        "type_locality": {"type": "geo_point"},
        "type_locality_name": {"type": "keyword"},
        "type_locality_country": {"type": "keyword"},
    }
}


def enrich_fields(rec: dict) -> dict:
    fields: dict = {"elements": rec["elements"]}
    if rec.get("location"):
        fields["type_locality"] = rec["location"]
        fields["type_locality_name"] = rec["type_locality_name"]
        fields["type_locality_country"] = rec["type_locality_country"]
    return fields


def main() -> None:
    es = es_client()
    props = json.load(open(PROPS_DIR / "minerals.json"))
    table = {name: enrich_fields(rec) for name, rec in props.items()}

    for index in (INDEX_SPECIES, INDEX_IMAGES):
        es.indices.put_mapping(index=index, **NEW_FIELDS)
        print(f"{index}: mapping 已追加新字段")

    from elasticsearch import helpers
    ok, _ = helpers.bulk(es, (
        {"_op_type": "update", "_index": INDEX_SPECIES, "_id": name,
         "doc": fields}
        for name, fields in table.items()
    ), raise_on_error=False)
    print(f"{INDEX_SPECIES}: 更新 {ok} 条")

    resp = es.update_by_query(
        index=INDEX_IMAGES,
        refresh=True,
        script={
            "lang": "painless",
            "source": """
                def f = params.table[ctx._source.species];
                if (f == null) { ctx.op = 'noop'; return; }
                for (entry in f.entrySet()) {
                    ctx._source[entry.getKey()] = entry.getValue();
                }
            """,
            "params": {"table": table},
        },
        conflicts="proceed",
        request_timeout=300,
    )
    print(f"{INDEX_IMAGES}: updated={resp['updated']} noop={resp['noops']} "
          f"conflicts={resp['version_conflicts']}")

    es.indices.refresh(index=INDEX_SPECIES)
    geo = es.count(index=INDEX_SPECIES,
                   query={"exists": {"field": "type_locality"}})["count"]
    agg = es.search(index=INDEX_IMAGES, size=0, aggs={
        "top_elements": {"terms": {"field": "elements", "size": 8}}})
    tops = [(b["key"], b["doc_count"])
            for b in agg["aggregations"]["top_elements"]["buckets"]]
    print(f"验证: species 带坐标 {geo}/98 | images 元素 top: {tops}")


if __name__ == "__main__":
    main()
