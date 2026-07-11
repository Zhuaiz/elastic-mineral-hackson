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
            # 保持 fp32：fp16 会让 xlm-roberta 文本塔数值溢出（实测全 NaN）。
            # 内存压力靠"查询走 ES 推理端点、本地模型仅兜底懒加载"化解。
            print(f"loading jinaai/jina-clip-v2 on {_device} ...")
            _model = AutoModel.from_pretrained(
                "jinaai/jina-clip-v2", trust_remote_code=True
            ).to(_device).eval()
    return _model


def _fall_back_to_cpu() -> None:
    global _model, _device
    with _lock:
        if _device != "cpu":
            print("⚠️ MPS 输出 NaN，永久降级到 CPU (fp32) 重算")
            _model = _model.to("cpu").float()
            _device = "cpu"




def _normalize(vecs) -> np.ndarray:
    arr = np.asarray(vecs, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=-1, keepdims=True)


def _encode_guarded(encode_once) -> np.ndarray:
    arr = np.asarray(encode_once(), dtype=np.float32)
    if np.isnan(arr).any():
        _fall_back_to_cpu()
        arr = np.asarray(encode_once(), dtype=np.float32)
        if np.isnan(arr).any():
            raise RuntimeError(
                "MPS 与 CPU 编码均输出 NaN——多为内存耗尽，"
                "关掉多余大进程后重启本服务")
    return _normalize(arr)


def encode_images(pil_images: list) -> np.ndarray:
    return _encode_guarded(lambda: load_model().encode_image(pil_images))


def encode_texts(texts: list[str], task: str = "retrieval.query") -> np.ndarray:
    return _encode_guarded(lambda: load_model().encode_text(texts, task=task))
