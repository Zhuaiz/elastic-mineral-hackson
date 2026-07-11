"""矿物鉴定演示服务：拖入标本照片 / 输入野外属性 → RRF 融合检索 → 候选矿物带图。

演示三种模式，直观展示"融合 > 单路"：
  - image: 只用照片（图像 kNN）
  - text:  只用属性文字（BM25）
  - rrf:   融合（图像 + 文字 + 硬度过滤），默认

前置: source .env（ES + basic auth）、embed_images + index_es 完成。
用法: .venv/bin/python demo/app.py  → 浏览器开 http://localhost:8000
仅用标准库 http.server + 已装的 torch/PIL/elasticsearch。
"""
import base64
import io
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from config import INDEX_IMAGES  # noqa: E402
from index_es import es_client  # noqa: E402

PORT = 8000
CONTEXT_K = 60  # 检索窗口要装得下热门种的重复文本（每种最多 ~30 张图共享同一段 props_text）
_es = None


def es():
    global _es
    if _es is None:
        _es = es_client()
    return _es


def bm25_leg(clue: str) -> dict:
    return {"standard": {"query": {"multi_match": {
        "query": clue, "fields": ["name^2", "props_text", "description"]}}}}


def knn_leg(vector: list[float]) -> dict:
    return {"knn": {"field": "image_vector", "query_vector": vector,
                    "k": 30, "num_candidates": 200}}


def run_search(mode: str, vector, clue, hardness) -> list[dict]:
    src = ["species", "props_text", "thumb", "crystal_system",
           "hardness_min", "hardness_max"]
    if mode == "image":
        body = {"size": CONTEXT_K, "_source": src, **knn_leg(vector)}
    elif mode == "text":
        body = {"size": CONTEXT_K, "_source": src,
                "query": bm25_leg(clue)["standard"]["query"]}
    else:  # rrf
        legs = []
        if clue:
            legs.append(bm25_leg(clue))
        if vector is not None:
            legs.append(knn_leg(vector))
        rrf = {"retrievers": legs, "rank_window_size": 100, "rank_constant": 20}
        if hardness:
            rrf["filter"] = [{"range": {"hardness_min": {"lte": hardness}}},
                             {"range": {"hardness_max": {"gte": hardness}}}]
        body = {"size": CONTEXT_K, "_source": src, "retriever": {"rrf": rrf}}
    hits = es().search(index=INDEX_IMAGES, **body)["hits"]["hits"]
    # 按种名聚合投票，返回候选（第一名即判定）
    agg: dict[str, dict] = {}
    for h in hits:
        s = h["_source"]
        sp = s["species"]
        a = agg.setdefault(sp, {"species": sp, "votes": 0, "score": h["_score"],
                                "thumb": s.get("thumb"), "props": s.get("props_text", ""),
                                "crystal_system": s.get("crystal_system"),
                                "hardness_min": s.get("hardness_min"),
                                "hardness_max": s.get("hardness_max")})
        a["votes"] += 1
    if mode == "text":
        # 文本腿：同种所有图共享同一段 props_text，票数只反映图片张数，按 BM25 分数排
        ranked = sorted(agg.values(), key=lambda x: -x["score"])
    else:
        ranked = sorted(agg.values(), key=lambda x: (-x["votes"], -x["score"]))
    return ranked[:8]


import os

EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "auto")  # es | local | auto
INFERENCE_EP = os.environ.get("INFERENCE_EP", "jina-clip-v2")
_es_embed_ok: bool | None = None  # auto 模式下记住 ES 端点是否可用
_IMG_PAYLOAD_STYLES = (
    lambda b64: {"input": [{"image": f"data:image/jpeg;base64,{b64}"}]},
    lambda b64: {"input": [{"content": {"type": "image", "format": "base64",
                                        "value": f"data:image/jpeg;base64,{b64}"}}]},
)


def _extract_vec(node):
    if isinstance(node, list):
        if node and all(isinstance(x, (int, float)) for x in node) and len(node) >= 64:
            return [float(x) for x in node]
        for item in node:
            if (v := _extract_vec(item)) is not None:
                return v
    elif isinstance(node, dict):
        for v in node.values():
            if (r := _extract_vec(v)) is not None:
                return r
    return None


def es_embed(image_b64: str | None, text: str | None) -> list[float]:
    """走 ES 推理端点（服务端调 jina-clip-v2），笔记本不跑模型。"""
    def call(payload):
        r = es().perform_request(
            "POST", f"/_inference/embedding/{INFERENCE_EP}", body=payload,
            headers={"content-type": "application/json",
                     "accept": "application/json"})
        vec = _extract_vec(r.body)
        if vec is None or len(vec) < 64:
            raise RuntimeError("推理端点响应里没有向量")
        return vec
    if image_b64:
        b64 = image_b64.split(",")[-1]
        last = None
        for style in _IMG_PAYLOAD_STYLES:
            try:
                return call(style(b64))
            except Exception as e:
                last = e
        raise last
    return call({"input": [text]})


def local_embed(image_b64: str | None, text: str | None) -> list[float]:
    from embedder import encode_images, encode_texts
    if image_b64:
        from PIL import Image
        raw = base64.b64decode(image_b64.split(",")[-1])
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        return encode_images([img])[0].tolist()
    return encode_texts([text])[0].tolist()


def embed(image_b64: str | None, text: str | None):
    global _es_embed_ok
    if not image_b64 and not text:
        return None
    if EMBED_BACKEND == "local":
        return local_embed(image_b64, text)
    if EMBED_BACKEND == "es" or _es_embed_ok in (None, True):
        try:
            vec = es_embed(image_b64, text)
            if _es_embed_ok is None:
                print("嵌入后端: ES 推理端点 ✓（全程 Elastic API）")
            _es_embed_ok = True
            return vec
        except Exception as e:
            if EMBED_BACKEND == "es":
                raise
            if _es_embed_ok is None:
                print(f"ES 推理端点不可用（{str(e)[:80]}），回落本地模型")
            _es_embed_ok = False
    return local_embed(image_b64, text)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (Path(__file__).parent / "index.html").read_bytes(),
                       "text/html; charset=utf-8")
        elif path.startswith("/thumb/"):
            fp = ROOT / "data" / "images" / path[len("/thumb/"):]
            if fp.exists() and fp.suffix == ".jpg":
                self._send(200, fp.read_bytes(), "image/jpeg")
            else:
                self._send(404, b"not found", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/search":
            return self._send(404, b"not found", "text/plain")
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        text = (req.get("text") or "").strip() or None
        hardness = req.get("hardness")
        try:
            vector = embed(req.get("image"), text)
            out = {}
            for mode in ("image", "text", "rrf"):
                if mode == "image" and vector is None:
                    continue
                if mode == "text" and not text:
                    continue
                out[mode] = run_search(mode, vector, text, hardness)
            self._send(200, json.dumps({"results": out}))
        except Exception as e:
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))


if __name__ == "__main__":
    print(f"矿物鉴定演示: http://localhost:{PORT}  (Ctrl+C 退出)")
    print("预热 jina-clip-v2（文本+图像两条路，触发 NaN 守卫）...")
    try:
        embed(None, "warmup")
        from PIL import Image
        probe = io.BytesIO()
        Image.new("RGB", (64, 64), (90, 160, 120)).save(probe, "JPEG")
        embed(base64.b64encode(probe.getvalue()).decode(), None)
        print("就绪。")
    except Exception as e:
        print(f"⚠️ 预热失败（{e}），服务照常启动，请求时守卫会再重试")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
