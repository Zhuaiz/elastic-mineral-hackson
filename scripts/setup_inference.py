"""在阿里云 ES 上创建 jinaai 多模态推理端点，并做向量空间一致性校验。

链路：查询 → ES /_inference/embedding/jina-clip-v2（服务端调 api.jina.ai）→ RRF。
笔记本不再跑模型；与索引里的向量同属 jina-clip-v2 空间（脚本会实测 parity）。

前置: source .env（需 ES_URL/ES_USER/ES_PASSWORD + JINA_API_KEY）
用法: .venv/bin/python scripts/setup_inference.py
"""
import base64
import json
import os
import sys

import numpy as np
import pyarrow.parquet as pq

from config import EMBED_DIR, ROOT
from index_es import es_client

INFERENCE_EP = "jina-clip-v2"
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")


def extract_vectors(resp_body) -> list[list[float]]:
    """兼容不同任务类型的响应外形，抠出所有 1024 维向量。"""
    def walk(node):
        if isinstance(node, list):
            if node and all(isinstance(x, (int, float)) for x in node) and len(node) >= 64:
                yield [float(x) for x in node]
            else:
                for item in node:
                    yield from walk(item)
        elif isinstance(node, dict):
            for v in node.values():
                yield from walk(v)
    return list(walk(resp_body))


def infer(es, payload: dict):
    r = es.perform_request(
        "POST", f"/_inference/embedding/{INFERENCE_EP}", body=payload,
        headers={"content-type": "application/json", "accept": "application/json"})
    return r.body


def main() -> None:
    if not JINA_API_KEY:
        sys.exit("先在 .env 里填 JINA_API_KEY（jina.ai 免费注册，1000 万 token）")
    es = es_client()

    # 幂等：存在即删除重建（api key 可能更新）
    try:
        es.perform_request("DELETE", f"/_inference/embedding/{INFERENCE_EP}",
                           headers={"accept": "application/json"})
        print(f"已删除旧端点 {INFERENCE_EP}")
    except Exception:
        pass
    es.perform_request(
        "PUT", f"/_inference/embedding/{INFERENCE_EP}",
        body={"service": "jinaai",
              "service_settings": {"api_key": JINA_API_KEY,
                                   "model_id": "jina-clip-v2",
                                   "similarity": "cosine"}},
        headers={"content-type": "application/json", "accept": "application/json"})
    print(f"端点 /_inference/embedding/{INFERENCE_EP} 创建 ✓")

    print("— 文本推理测试 …")
    vecs = extract_vectors(infer(es, {"input": ["green mineral with green streak"]}))
    assert vecs and len(vecs[0]) == 1024, f"文本向量异常: {len(vecs)} 个/维度 {len(vecs[0]) if vecs else 0}"
    print(f"  文本 ✓ 1024 维")

    print("— 图像推理测试（两种载荷格式自动探测）…")
    rows = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    probe = rows[0]
    img_path = ROOT / probe["thumb"]
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    img_vec = None
    for payload in (
        {"input": [{"image": f"data:image/jpeg;base64,{b64}"}]},
        {"input": [{"content": {"type": "image", "format": "base64",
                                "value": f"data:image/jpeg;base64,{b64}"}}]},
    ):
        try:
            got = extract_vectors(infer(es, payload))
            if got and len(got[0]) == 1024:
                img_vec = np.array(got[0], dtype=np.float32)
                print(f"  图像 ✓ 载荷格式: {list(payload['input'][0].keys())}")
                break
        except Exception as e:
            print(f"  载荷格式不适用: {str(e)[:100]}")
    assert img_vec is not None, "两种图像载荷格式都失败——把上面的报错发我"

    print("— 向量空间一致性（ES端点 vs 索引内本地向量）…")
    local = np.array(probe["vector"], dtype=np.float32)
    local /= np.linalg.norm(local)
    remote = img_vec / np.linalg.norm(img_vec)
    cos = float(local @ remote)
    print(f"  同一张图 cosine = {cos:.4f}  ({probe['species']}, {probe['id']})")
    if cos < 0.98:
        print("  ⚠️ 低于 0.98：注意缩略图 vs 原图差异，或空间不一致——发我数值")
    else:
        print("  同空间确认 ✓ 查询可放心走 ES 端点")


if __name__ == "__main__":
    main()
