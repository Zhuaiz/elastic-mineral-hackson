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
CONTEXT_K = 12
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
        rrf = {"retrievers": legs, "rank_window_size": 50, "rank_constant": 20}
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
    return sorted(agg.values(), key=lambda x: (-x["votes"], -x["score"]))[:8]


def embed(image_b64: str | None, text: str | None):
    from embedder import encode_images, encode_texts
    if image_b64:
        from PIL import Image
        raw = base64.b64decode(image_b64.split(",")[-1])
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        return encode_images([img])[0].tolist()
    if text:
        return encode_texts([text])[0].tolist()
    return None


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
    print("预热 jina-clip-v2 ...")
    embed(None, "warmup")
    print("就绪。")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
