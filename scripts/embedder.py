"""jina-clip-v2 加载与编码的统一入口（绕开 sentence-transformers 的模态限制）。"""
import numpy as np

import compat  # noqa: F401  transformers 5.x 垫片，须在模型加载前

_model = None


def load_model():
    global _model
    if _model is None:
        import torch
        from transformers import AutoModel
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"loading jinaai/jina-clip-v2 on {device} ...")
        _model = AutoModel.from_pretrained(
            "jinaai/jina-clip-v2", trust_remote_code=True
        ).to(device).eval()
    return _model


def _normalize(vecs) -> np.ndarray:
    arr = np.asarray(vecs, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=-1, keepdims=True)


def encode_images(pil_images: list) -> np.ndarray:
    return _normalize(load_model().encode_image(pil_images))


def encode_texts(texts: list[str], task: str = "retrieval.query") -> np.ndarray:
    return _normalize(load_model().encode_text(texts, task=task))
