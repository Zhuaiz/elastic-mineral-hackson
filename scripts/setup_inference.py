"""创建 ES jinaai 文本推理端点 + 校验 Jina API 图像嵌入，两路都与索引同空间。

9.3.2 的 jinaai 服务只支持 text_embedding/rerank（多模态 embedding 任务是更新版本），
所以：文本查询 → ES /_inference/text_embedding/jina-clip-v2（服务端调 Jina）；
图像查询 → 直调 api.jina.ai（同 key 同模型同空间）。笔记本零模型。

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


def jina_api(payload: dict) -> dict:
    import urllib.request
    req = urllib.request.Request(
        "https://api.jina.ai/v1/embeddings",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {JINA_API_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main() -> None:
    if not JINA_API_KEY:
        sys.exit("先在 .env 里填 JINA_API_KEY（jina.ai 免费注册，1000 万 token）")
    es = es_client()

    # 幂等：存在即删除重建（api key 可能更新）
    try:
        es.perform_request("DELETE", f"/_inference/text_embedding/{INFERENCE_EP}",
                           headers={"accept": "application/json"})
        print(f"已删除旧端点 {INFERENCE_EP}")
    except Exception:
        pass
    es.perform_request(
        "PUT", f"/_inference/text_embedding/{INFERENCE_EP}",
        body={"service": "jinaai",
              "service_settings": {"api_key": JINA_API_KEY,
                                   "model_id": "jina-clip-v2",
                                   "similarity": "cosine"}},
        headers={"content-type": "application/json", "accept": "application/json"})
    print(f"端点 /_inference/text_embedding/{INFERENCE_EP} 创建 ✓")

    print("— ES 端点文本推理（服务端出网调 Jina）…")
    r = es.perform_request(
        "POST", f"/_inference/text_embedding/{INFERENCE_EP}",
        body={"input": ["green mineral with green streak"]},
        headers={"content-type": "application/json", "accept": "application/json"})
    text_vecs = extract_vectors(r.body)
    assert text_vecs and len(text_vecs[0]) == 1024, "ES 端点文本向量异常"
    print("  文本经 ES ✓ 1024 维（阿里云 ES 出公网可达 api.jina.ai）")

    print("— Jina API 直调图像嵌入 …")
    rows = pq.read_table(EMBED_DIR / "embeddings.parquet").to_pylist()
    probe = rows[0]
    b64 = base64.b64encode((ROOT / probe["thumb"]).read_bytes()).decode()
    resp = jina_api({"model": "jina-clip-v2",
                     "input": [{"image": f"data:image/jpeg;base64,{b64}"}]})
    img_vec = np.array(extract_vectors(resp)[0], dtype=np.float32)
    print("  图像经 Jina API ✓ 1024 维")

    print("— 向量空间一致性（云端 vs 索引内本地向量）…")
    local = np.array(probe["vector"], dtype=np.float32)
    local /= np.linalg.norm(local)
    remote = img_vec / np.linalg.norm(img_vec)
    cos = float(local @ remote)
    print(f"  同一张图 cosine = {cos:.4f}  ({probe['species']}, {probe['id']})")
    if cos < 0.98:
        print("  ⚠️ 低于 0.98：缩略图 vs 原图差异或空间不一致——发我数值")
    else:
        print("  同空间确认 ✓ 查询放心走云端")


if __name__ == "__main__":
    main()
