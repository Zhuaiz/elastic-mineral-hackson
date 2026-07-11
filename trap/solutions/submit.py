"""判分 + 构建 report.json + tp submit 上传一个 solution 的跑分。

用法: python3 trap/solutions/submit.py <config> "<engine>" "<strategy>"
  config: answers/<config>.txt 里的 id|answer（每行）
输出: 本地准确率 + report.json，并调用 tp submit mineral-id --report ...
"""
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TASK = ROOT / "trap" / "task"
SOL = Path(__file__).resolve().parent
TASK_ID = "mineral-species-id"
REPO = "https://github.com/Zhuaiz/elastic-mineral-hackson"


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


def main() -> None:
    config, engine, strategy = sys.argv[1], sys.argv[2], sys.argv[3]
    answers = {}
    for line in (SOL / "answers" / f"{config}.txt").read_text().splitlines():
        if "|" in line:
            cid, ans = line.split("|", 1)
            answers[cid.strip()] = ans.strip()

    work = SOL / "_work" / config
    cases, n_pass = [], 0
    for cid, ans in answers.items():
        metrics = judge_case(cid, ans, work)
        n_pass += int(metrics["score"] == 1.0)
        cases.append({"case_id": cid, "exit_code": 0, "duration": None,
                      "metrics": metrics, "skipped": False})

    acc = n_pass / len(cases)
    print(f"[{config}] {n_pass}/{len(cases)} = {acc:.1%}")

    # prod 的 wire 格式（比 tp 0.4.0 新）：cases_results + provenance，POST /api/submit。
    # tp CLI 仍用旧的 /api/submit/{task} 路径（prod 上 404），故直接构造并 POST。
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    report = {
        "task_id": TASK_ID, "cases_results": cases,
        "started_at": now, "finished_at": now,
        "provenance": {"task": {"repo": REPO, "commit": commit},
                       "solution": {"repo": REPO, "commit": commit}},
        "metadata": {"engine": engine, "framework": "elastic-agenthack",
                     "strategy": strategy, "model": "qwen-plus"},
    }
    report_path = SOL / f"wire_{config}.json"
    json.dump(report, open(report_path, "w"), indent=2)

    import os
    import urllib.request
    key = os.environ.get("TP_API_KEY") or json.load(
        open(os.path.expanduser("~/.config/trapstreet/auth.json")))["api_key"]
    print(f"submitting {report_path.name} to prod /api/submit ...")
    req = urllib.request.Request(
        "https://trapstreet.run/api/submit", data=report_path.read_bytes(),
        headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        run = json.loads(resp.read()).get("run", {})
    print(f"  ok -> score {run.get('score')} ({run.get('cases_passed')}/{run.get('cases_total')})")
    print(f"  https://trapstreet.run/tasks/{TASK_ID}")


if __name__ == "__main__":
    main()
