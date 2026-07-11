"""判分 + 构建 prod wire report + POST /api/submit 上传一个 solution 的跑分。

用法:
  python3 trap/solutions/submit.py <config> --engine "..." --strategy "..." \
      [--solution-commit <sha>] [--model qwen-plus]
  config: 读 answers/<config>.txt 的 id|answer（每行）

trapstreet prod 契约（tp CLI 0.4.0 的提交路径已过时，prod 返回 404）:
  - POST https://trapstreet.run/api/submit，Authorization: Bearer <api_key>
  - body: cases_results 数组 + provenance.task/.solution 的 {repo, commit}
  - provenance.task.commit 必须匹配平台已发布的任务版本
    （自动从 GET /api/tasks/<id> 读 latest.commit_sha —— 不能用本地 HEAD）
  - solution 身份 = (repo, commit)：想在榜单各占一行，每个配置要用
    一个不同的、已推送到公开仓库的 commit（--solution-commit）
  - 榜单 ENGINE 列 = profile.model[0]（只在 solution 首次创建时落库）；
    LATENCY 列 = started_at_utc→finished_at_utc 墙钟毫秒（缺省时回退
    per-case duration 求和）。metadata.* 不在 wire 格式里，会被忽略。
  - timing 优先读 eval 产出的 trap/eval/results/run_meta.json（accuracy_
    vs_retrieval.py 生成）；没有则起止都用当前时刻（latency 记 0，慎用）。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TASK = ROOT / "trap" / "task"
SOL = Path(__file__).resolve().parent
TASK_ID = "mineral-species-id"
REPO = "https://github.com/Zhuaiz/elastic-mineral-hackson"
SERVER = "https://trapstreet.run"


def judge_case(case_id: str, answer: str, work: Path) -> dict:
    d = work / case_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "stdout").write_text(answer)
    (d / "meta.json").write_text('{"exit_code": 0}')
    payload = {
        "outputs": {"case_stdout": str(d / "stdout"), "case_meta.json": str(d / "meta.json")},
        "expected": {"answer.json": str(TASK / "expected" / case_id / "answer.json")},
    }
    out = subprocess.run(
        ["python3", str(TASK / "judge.py")],
        env={"TRAPTASK_PAYLOAD": json.dumps(payload), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def published_task_commit() -> str:
    """平台上该任务已发布版本的 commit——provenance.task.commit 必须匹配它。"""
    with urllib.request.urlopen(f"{SERVER}/api/tasks/{TASK_ID}", timeout=30) as r:
        return json.load(r)["task"]["latest"]["commit_sha"]


def ensure_pushed(commit: str) -> None:
    """solution commit 必须已在公开仓库可见，否则平台校验会拒。"""
    subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=ROOT, check=True)
    ok = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/main"],
        cwd=ROOT).returncode == 0
    if not ok:
        raise SystemExit(
            f"commit {commit[:10]} 不在 origin/main 上——先 git push 再提交。")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="answers/<config>.txt")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--model", default="qwen-plus")
    ap.add_argument("--solution-commit", default=None,
                    help="该 solution 的身份 commit（默认 HEAD；不同配置须不同）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只本地判分打印分数，不校验推送、不 POST（无需 api_key）")
    args = ap.parse_args()

    answers = {}
    for line in (SOL / "answers" / f"{args.config}.txt").read_text().splitlines():
        if "|" in line:
            cid, ans = line.split("|", 1)
            answers[cid.strip()] = ans.strip()

    expected_ids = sorted(p.name for p in (TASK / "expected").iterdir() if p.is_dir())
    missing = set(expected_ids) - set(answers)
    if missing:
        raise SystemExit(f"answers/{args.config}.txt 缺 {len(missing)} 个 case: {sorted(missing)}")

    # timing：eval 会把每配置的起止时间 + 每 case 耗时写到 run_meta.json
    meta_path = ROOT / "trap" / "eval" / "results" / "run_meta.json"
    timing = {}
    if meta_path.exists():
        timing = json.load(open(meta_path)).get(args.config, {})
    if not timing:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        timing = {"started_at_utc": now, "finished_at_utc": now, "durations": {}}
        print("⚠️ 无 run_meta.json timing，latency 将记 0")
    durations = timing.get("durations", {})

    work = SOL / "_work" / args.config
    cases, n_pass = [], 0
    for cid, ans in answers.items():
        metrics = judge_case(cid, ans, work)
        n_pass += int(metrics["score"] == 1.0)
        cases.append({"case_id": cid, "exit_code": 0,
                      "duration": durations.get(cid),
                      "metrics": metrics, "skipped": False})

    acc = n_pass / len(cases)
    print(f"[{args.config}] {n_pass}/{len(cases)} = {acc:.1%}")

    if args.dry_run:
        print("  (--dry-run：仅本地判分，未提交)")
        return

    solution_commit = args.solution_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    ensure_pushed(solution_commit)
    task_commit = published_task_commit()

    report = {
        "task_id": TASK_ID, "cases_results": cases,
        "started_at_utc": timing["started_at_utc"],
        "finished_at_utc": timing["finished_at_utc"],
        "provenance": {"task": {"repo": REPO, "commit": task_commit},
                       "solution": {"repo": REPO, "commit": solution_commit}},
        # profile.model[0] → 榜单 ENGINE 列（solution 首建时落库）
        "profile": {"model": [args.engine], "framework": ["elastic-agenthack"]},
        "environment": {"strategy": args.strategy, "answer_model": args.model,
                        "retrieval_config": args.config},
    }
    report_path = SOL / f"wire_{args.config}.json"
    json.dump(report, open(report_path, "w"), indent=2)

    key = os.environ.get("TP_API_KEY") or json.load(
        open(os.path.expanduser("~/.config/trapstreet/auth.json")))["api_key"]
    print(f"submitting {report_path.name} (solution={solution_commit[:10]}) ...")
    req = urllib.request.Request(
        f"{SERVER}/api/submit", data=report_path.read_bytes(),
        headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            run = json.loads(resp.read()).get("run", {})
    except urllib.error.HTTPError as e:
        print(f"  提交被拒 HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  ok -> score {run.get('score')} ({run.get('cases_passed')}/{run.get('cases_total')})")
    print(f"  {SERVER}/tasks/{TASK_ID}")


if __name__ == "__main__":
    main()
