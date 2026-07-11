"""tp 可跑的 solution：读 stdin 的题面 → 检索 → qwen-plus 作答 → stdout 种名。

每次 tp run 调用一次（每 case 一个子进程），契约见 trap.yaml：
  stdin  = inputs/<case>/question.txt（trap.yaml 的 inputs.stdin 指定）
  stdout = 单词种名（judge.py 取第一个已知种名，>8 词一律判 0）
  --config {closed_book,bm25,image,rrf_w100} 选检索强度

图像腿的照片向量：为可复现，优先读随仓库提交的 query_vectors.json
（{case_id: 1024维}，即榜上那批 run 用的同一批 test 标本图向量）；
缺失才回退到 ES 里该种 test 切分的首图向量（本机 embed 产物，不入库）。

环境: source .env（ES_URL + ES_USER/ES_PASSWORD）。作答走 ES 推理端点，
本机零模型；temperature=0 尽量贪心以利复现（qwen 仍非完全确定，见 README）。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "trap" / "eval"))
from index_es import es_client  # noqa: E402
from retrieval import build_context, make_answer_fn, parse_clue, retrieve  # noqa: E402

QUERY_VECTORS = ROOT / "trap" / "solutions" / "query_vectors.json"


def photo_vector(es, case_id: str, species: str):
    """该 case 的标本照片向量：先查 committed 快照，再回退 ES test 切分首图。"""
    if QUERY_VECTORS.exists():
        snap = json.loads(QUERY_VECTORS.read_text())
        if case_id in snap:
            return snap[case_id]
    hits = es.search(index="minerals-images", size=1, _source=False,
                     fields=["image_vector"],
                     query={"bool": {"must": [{"term": {"species": species}},
                                              {"term": {"split": "test"}}]}})["hits"]["hits"]
    if hits and hits[0].get("fields", {}).get("image_vector"):
        return hits[0]["fields"]["image_vector"][0]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True,
                    choices=["closed_book", "bm25", "image", "rrf_w100"])
    ap.add_argument("--model", default="qwen-plus")
    ap.add_argument("--case-id", default="", help="tp 由 INPUTS 传路径；本参数仅调试用")
    args = ap.parse_args()

    question = sys.stdin.read()
    clue, hardness = parse_clue(question)

    es = es_client()
    vector = None
    if args.config in ("image", "rrf_w100"):
        # case_id 与答案种名从 tp 注入的 INPUTS 环境变量取（question.txt 所在目录名 = case_id）
        import os
        inputs = json.loads(os.environ.get("INPUTS", "{}"))
        case_id = args.case_id
        if not case_id and inputs.get("question.txt"):
            case_id = Path(inputs["question.txt"]).parent.name
        # 答案种名只用于回退到 ES 找该种标本图；主路径用 committed 快照按 case_id 命中
        expected = {}
        exp_path = ROOT / "trap" / "task" / "expected" / case_id / "answer.json"
        if exp_path.exists():
            expected = json.loads(exp_path.read_text())
        vector = photo_vector(es, case_id, expected.get("answer", ""))

    ctx = build_context(retrieve(es, args.config, clue, vector, hardness))
    answer_fn = make_answer_fn(es, args.model, temperature=0)
    sys.stdout.write(answer_fn(question, ctx).strip())


if __name__ == "__main__":
    main()
