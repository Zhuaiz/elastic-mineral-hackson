"""transformers 5.x 兼容垫片 + MPS NaN 修复。

必须在 torch / AutoModel 加载模型之前 import 本模块。
1. jina-clip-v2 远程代码 import 了 transformers 5.x 已移除的 clip_loss（仅推理不触发 loss，垫上即可）。
2. jina-clip-v2 视觉塔在 Apple MPS 上会产出全 NaN 向量；PYTORCH_ENABLE_MPS_FALLBACK
   把出问题的算子回退到 CPU，既修好 NaN 又保住 MPS 速度（~1.5 img/s）。须在 torch 初始化前设置。
"""
import os

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from transformers.models.clip import modeling_clip

if not hasattr(modeling_clip, "clip_loss"):
    def _clip_loss(similarity):
        caption_loss = modeling_clip.contrastive_loss(similarity)
        image_loss = modeling_clip.contrastive_loss(similarity.t())
        return (caption_loss + image_loss) / 2.0

    modeling_clip.clip_loss = _clip_loss
