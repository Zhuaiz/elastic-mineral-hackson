"""抓取矿物属性数据：Wikipedia REST 摘要（无需 key）+ Mindat API（需 MINDAT_API_KEY）。

用法:
  python3 scripts/fetch_properties.py wikipedia   # 98 类摘要 -> data/properties/wikipedia.json
  python3 scripts/fetch_properties.py mindat      # IMA dump + 逐名兜底 -> data/properties/mindat.json
  python3 scripts/fetch_properties.py merge       # 合并 -> data/properties/minerals.json
仅用标准库，venv 未建好也能跑。
"""
import json
import sys
import time
import urllib.parse
import urllib.request

from config import (MINDAT_API_KEY, PROPS_DIR, all_canonical_names)

UA = {"User-Agent": "es-agenthack-mineral-demo/0.1 (hackathon prep)"}
WIKI_TITLE_OVERRIDES = {"lapis lazuli": "Lapis lazuli"}
MINDAT_FIELDS = (
    "id,name,ima_formula,mindat_formula,csystem,hmin,hmax,streak,colour,"
    "lustre,lustretype,dmeas,dcalc,diapheny,cleavage,fracturetype,description_short"
)


def get_json(url: str, headers: dict, retries: int = 3) -> dict | None:
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"  ! attempt {attempt + 1} {url.split('?')[0][-60:]}: {e}",
                  file=sys.stderr)
            time.sleep(2 ** attempt)
    return None


def fetch_wikipedia() -> None:
    path = PROPS_DIR / "wikipedia.json"
    out = json.load(open(path)) if path.exists() else {}
    todo = [n for n in all_canonical_names() if n not in out]
    print(f"已有 {len(out)}，待抓 {len(todo)}")
    for name in todo:
        title = WIKI_TITLE_OVERRIDES.get(name, name).capitalize()
        j = get_json(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(title.replace(" ", "_")),
            UA,
        )
        if j and j.get("extract"):
            out[name] = {"title": j.get("title"), "extract": j["extract"],
                         "description": j.get("description", "")}
            print(f"  ok {name} ({len(j['extract'])} chars)")
        else:
            print(f"  MISS {name}")
        time.sleep(0.5)
    PROPS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(PROPS_DIR / "wikipedia.json", "w"), ensure_ascii=False, indent=1)
    print(f"wikipedia.json: {len(out)}/{len(all_canonical_names())} 个种有摘要")


def fetch_mindat() -> None:
    if not MINDAT_API_KEY:
        sys.exit("先设置 MINDAT_API_KEY 环境变量（mindat.org 注册后在个人页拿 token）")
    headers = {**UA, "Authorization": f"Token {MINDAT_API_KEY}"}
    wanted = {n.lower() for n in all_canonical_names()}
    found: dict[str, dict] = {}

    url = (f"https://api.mindat.org/v1/geomaterials/?ima=1&fields={MINDAT_FIELDS}"
           f"&page-size=1500&format=json")
    while url:
        j = get_json(url, headers)
        if not j:
            break
        for rec in j.get("results", []):
            n = (rec.get("name") or "").lower()
            if n in wanted:
                found[n] = rec
        url = j.get("next")
        print(f"  ima dump: 已匹配 {len(found)}/{len(wanted)}")

    for name in sorted(wanted - set(found)):
        j = get_json(
            f"https://api.mindat.org/v1/geomaterials/?name={urllib.parse.quote(name)}"
            f"&fields={MINDAT_FIELDS}&format=json",
            headers,
        )
        results = (j or {}).get("results", [])
        if results:
            found[name] = results[0]
            print(f"  按名兜底 ok: {name}")
        else:
            print(f"  Mindat 无记录: {name}（用 Wikipedia 属性）")
        time.sleep(0.3)

    PROPS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(found, open(PROPS_DIR / "mindat.json", "w"), ensure_ascii=False, indent=1)
    print(f"mindat.json: {len(found)}/{len(wanted)}")


def merge() -> None:
    wiki = json.load(open(PROPS_DIR / "wikipedia.json"))
    mindat_path = PROPS_DIR / "mindat.json"
    mindat = json.load(open(mindat_path)) if mindat_path.exists() else {}
    merged = {}
    for name in all_canonical_names():
        m = mindat.get(name.lower(), {})
        w = wiki.get(name, {})
        hardness_min = m.get("hmin")
        hardness_max = m.get("hmax") or hardness_min
        rec = {
            "species": name,
            "formula": m.get("ima_formula") or m.get("mindat_formula") or "",
            "crystal_system": m.get("csystem") or "",
            "hardness_min": hardness_min,
            "hardness_max": hardness_max,
            "streak": m.get("streak") or "",
            "color": m.get("colour") or "",
            "luster": m.get("lustre") or m.get("lustretype") or "",
            "density": m.get("dmeas") or m.get("dcalc") or None,
            "diaphaneity": m.get("diapheny") or "",
            "cleavage": m.get("cleavage") or "",
            "fracture": m.get("fracturetype") or "",
            "short_description": m.get("description_short") or "",
            "wikipedia": w.get("extract", ""),
        }
        parts = [f"{name}."]
        if rec["formula"]:
            parts.append(f"Chemical formula {rec['formula']}.")
        if rec["crystal_system"]:
            parts.append(f"Crystal system {rec['crystal_system']}.")
        if hardness_min:
            parts.append(f"Mohs hardness {hardness_min}"
                         + (f"-{hardness_max}." if hardness_max and hardness_max != hardness_min else "."))
        for label, key in [("Streak", "streak"), ("Color", "color"), ("Luster", "luster"),
                           ("Diaphaneity", "diaphaneity"), ("Cleavage", "cleavage")]:
            if rec[key]:
                parts.append(f"{label}: {rec[key]}.")
        if rec["density"]:
            parts.append(f"Specific gravity {rec['density']}.")
        rec["props_text"] = " ".join(parts)
        merged[name] = rec
    json.dump(merged, open(PROPS_DIR / "minerals.json", "w"), ensure_ascii=False, indent=1)
    with_mindat = sum(1 for r in merged.values() if r["crystal_system"])
    with_wiki = sum(1 for r in merged.values() if r["wikipedia"])
    print(f"minerals.json: {len(merged)} 种 | mindat 结构化 {with_mindat} | wikipedia 文本 {with_wiki}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "wikipedia"
    {"wikipedia": fetch_wikipedia, "mindat": fetch_mindat, "merge": merge}[cmd]()
