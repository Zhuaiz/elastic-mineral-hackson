"""用 jina-clip-v2 (MPS) 嵌入矿物图片，导出缩略图供 demo UI 使用。

用法:
  .venv/bin/python scripts/embed_images.py --dry-run 100        # 计时测试
  .venv/bin/python scripts/embed_images.py                      # 全量 (val+test 5,498 张)
  .venv/bin/python scripts/embed_images.py --per-class 30       # 每类最多 30 张

输出:
  data/embeddings/embeddings.parquet  (id, class_raw, species, split, vector[1024], thumb)
  data/images/<species>/<id>.jpg      (384px 缩略图)
"""
import argparse
import io
import time

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

from config import (CLASS_NAMES, EMBED_DIMS, EMBED_MODEL, EMBED_DIR,
                    IMAGES_DIR, PARQUET_DIR, canonical)

THUMB_SIZE = 384
BATCH = 8


def iter_rows(per_class: int | None):
    counts: dict[str, int] = {}
    for pf in sorted(PARQUET_DIR.glob("*.parquet")):
        split = pf.name.split("-")[0]
        table = pq.read_table(pf)
        for i in range(table.num_rows):
            label_id = table["name"][i].as_py()
            raw = CLASS_NAMES[label_id]
            if per_class is not None:
                if counts.get(raw, 0) >= per_class:
                    continue
                counts[raw] = counts.get(raw, 0) + 1
            img_bytes = table["image"][i]["bytes"].as_py()
            yield {"split": split, "class_raw": raw, "bytes": img_bytes,
                   "row": f"{split}-{i:05d}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", type=int, default=None, metavar="N")
    ap.add_argument("--per-class", type=int, default=None)
    args = ap.parse_args()

    from embedder import encode_images

    EMBED_DIR.mkdir(parents=True, exist_ok=True)
    records, batch_imgs, batch_meta = [], [], []
    t0 = time.time()
    n = 0

    def flush():
        nonlocal records
        if not batch_imgs:
            return
        vecs = encode_images(batch_imgs)
        for meta, vec in zip(batch_meta, vecs):
            records.append({**meta, "vector": vec.tolist()})
        batch_imgs.clear()
        batch_meta.clear()

    for row in iter_rows(args.per_class):
        img = Image.open(io.BytesIO(row["bytes"])).convert("RGB")
        species = canonical(row["class_raw"])
        thumb_dir = IMAGES_DIR / species
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{row['row']}.jpg"
        if not thumb_path.exists():
            t = img.copy()
            t.thumbnail((THUMB_SIZE, THUMB_SIZE))
            t.save(thumb_path, "JPEG", quality=85)
        batch_imgs.append(img)
        batch_meta.append({"id": row["row"], "class_raw": row["class_raw"],
                           "species": species, "split": row["split"],
                           "thumb": str(thumb_path.relative_to(IMAGES_DIR.parent.parent))})
        if len(batch_imgs) >= BATCH:
            flush()
        n += 1
        if n % 200 == 0:
            dt = time.time() - t0
            print(f"  {n} imgs, {n/dt:.2f} img/s, elapsed {dt/60:.1f} min")
        if args.dry_run and n >= args.dry_run:
            break
    flush()

    dt = time.time() - t0
    print(f"done: {n} images in {dt/60:.1f} min ({n/dt:.2f} img/s)")
    if args.dry_run:
        total = 5498
        print(f"[dry-run] 推算 val+test 全量 {total} 张约 {total/(n/dt)/60:.0f} 分钟")
    schema = pa.schema([
        ("id", pa.string()), ("class_raw", pa.string()), ("species", pa.string()),
        ("split", pa.string()), ("thumb", pa.string()),
        ("vector", pa.list_(pa.float32(), EMBED_DIMS)),
    ])
    table = pa.Table.from_pylist(records, schema=schema)
    out = EMBED_DIR / ("embeddings-dryrun.parquet" if args.dry_run else "embeddings.parquet")
    pq.write_table(table, out)
    print(f"wrote {out} ({table.num_rows} rows)")


if __name__ == "__main__":
    main()
