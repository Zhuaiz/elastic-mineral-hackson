"""项目共享配置：路径、类别表、归一化映射、ES/模型参数。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PARQUET_DIR = DATA / "parquet"
IMAGES_DIR = DATA / "images"
PROPS_DIR = DATA / "properties"
EMBED_DIR = DATA / "embeddings"

EMBED_MODEL = "jinaai/jina-clip-v2"
EMBED_DIMS = 1024

ES_URL = os.environ.get("ES_URL", "")
ES_API_KEY = os.environ.get("ES_API_KEY", "")
ES_USER = os.environ.get("ES_USER", "")
ES_PASSWORD = os.environ.get("ES_PASSWORD", "")
MINDAT_API_KEY = os.environ.get("MINDAT_API_KEY", "")

INDEX_IMAGES = "minerals-images"
INDEX_SPECIES = "minerals-species"

# 数据集原始标签 -> 规范种名（Fersman 博物馆数据的俄语转写修正）
NORMALIZE = {
    "analcim": "analcime",
    "antimonite": "stibnite",
    "cancrinit": "cancrinite",
    "cobaltin": "cobaltite",
    "credit": "creedite",
    "elbait": "elbaite",
    "labrador": "labradorite",
    "nephritis": "nephrite",
    "scheelit": "scheelite",
    "vesuvian": "vesuvianite",
}

# 变种/岩石/非 IMA 种：Mindat ima=1 过滤会漏掉，属性以 Wikipedia 为准
VARIETIES = {
    "agate", "amazonite", "amber", "amethyst", "carnelian", "chalcedony",
    "chrysoprase", "flint", "hornblende", "jasper", "lapis lazuli",
    "limonite", "labradorite", "nephrite",
}

def load_class_names() -> list[str]:
    """98 个原始类别标签（ClassLabel 顺序即 id 顺序），来自数据集 features。"""
    import json
    return json.load(open(DATA / "class_names.json"))


CLASS_NAMES = load_class_names()


def canonical(raw_label: str) -> str:
    return NORMALIZE.get(raw_label, raw_label)


def all_canonical_names() -> list[str]:
    return sorted({canonical(n) for n in CLASS_NAMES})
