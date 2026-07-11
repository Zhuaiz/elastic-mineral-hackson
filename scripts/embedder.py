"""jina-clip-v2 加载与编码的统一入口（绕开 sentence-transformers 的模态限制）。

可靠性策略：MPS 提速，但每次编码后做 NaN 守卫——jina-clip-v2 的视觉塔在 MPS 上
（尤其非主线程，如 demo 的 HTTP 处理线程）会偶发输出全 NaN。一旦检出，
整个进程永久降级到 CPU 重算（单张查询图 CPU ~2s，演示够用；批量入库仍走 MPS）。
强制 CPU: 设环境变量 EMBED_DEVICE=cpu。
"""
import os
import threading

import numpy as np

import compat  # noqa: F401  transformers 5.x 垫片，须在模型加载前

_model = None
_device = None
_lock = threading.Lock()


def load_model():
    global _model, _device
    with _lock:
        if _model is None:
            import torch
            from transformers import AutoModel
            _device = os.environ.get("EMBED_DEVICE") or (
                "mps" if torch.backends.mps.is_available() else "cpu")
            # fp16 内存减半（16GB 机器上必须），CPU 走 fp32 保数值稳定
            dtype = torch.float16 if _device == "mps" else torch.float32
            print(f"loading jinaai/jina-clip-v2 on {_device} ({dtype}) ...")
            _model = AutoModel.from_pretrained(
                "jinaai/jina-clip-v2", trust_remote_code=True, dtype=dtype
            ).to(_device).eval()
    return _model


def _fall_back_to_cpu() -> None:
    global _model, _device
    with _lock:
        if _device != "cpu":
            print("⚠️ MPS 输出 NaN，永久降级到 CPU (fp32) 重算")
            _model = _model.to("cpu").float()
            _device = "cpu"


def _reload_model() -> None:
    """内存紧张时 CPU 推理也可能出 NaN；释放后整模重载是最后一道防线。"""
    global _model
    with _lock:
        print("⚠️ CPU 重算仍 NaN，释放并重载模型 ...")
        _model = None
    load_model()


def _normalize(vecs) -> np.ndarray:
    arr = np.asarray(vecs, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=-1, keepdims=True)


def _encode_guarded(encode_once) -> np.ndarray:
    arr = np.asarray(encode_once(), dtype=np.float32)
    if np.isnan(arr).any():
        _fall_back_to_cpu()
        arr = np.asarray(encode_once(), dtype=np.float32)
    if np.isnan(arr).any():
        _reload_model()
        arr = np.asarray(encode_once(), dtype=np.float32)
        if np.isnan(arr).any():
            raise RuntimeError(
                "编码连续 3 次输出 NaN——多为内存耗尽，关掉多余的大进程后重试")
    return _normalize(arr)


def encode_images(pil_images: list) -> np.ndarray:
    return _encode_guarded(lambda: load_model().encode_image(pil_images))


def encode_texts(texts: list[str], task: str = "retrieval.query") -> np.ndarray:
    return _encode_guarded(lambda: load_model().encode_text(texts, task=task))
