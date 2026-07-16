"""Overall grader for the mineral-id task (trapstreet contract).

Aggregates per-case judge results into a run-level verdict. Reads the case list
from $TRAPTASK_MANIFEST and emits JSON on stdout with `passed`, `score`
(accuracy), per-category breakdown, and latency stats — the leaderboard reads
these. Pass threshold = 60% (fine-grained 98-way mineral ID is hard).
"""
from __future__ import annotations

import json
import os
from collections import Counter

PASS_THRESHOLD = 0.60


def main() -> None:
    cases = json.loads(os.environ["TRAPTASK_MANIFEST"])

    scored = [c for c in cases if c.get("metrics") and c["metrics"].get("score") is not None]
    skipped = [c for c in cases if not c.get("metrics") or c["metrics"].get("score") is None]
    accuracy = (sum(c["metrics"]["score"] for c in scored) / len(scored)) if scored else 0.0

    by_score: Counter[str] = Counter()
    by_total: Counter[str] = Counter()
    for c in scored:
        cat = c["metrics"].get("difficulty") or c["metrics"].get("category")
        if cat:
            by_total[cat] += 1
            by_score[cat] += c["metrics"]["score"]
    by_category_pct = {k: round(by_score[k] / by_total[k], 3) for k in by_total}

    durations = [c.get("duration", 0.0) for c in cases if c.get("duration") is not None]
    if durations:
        ds = sorted(durations)
        latency_ms_median = round(ds[len(ds) // 2] * 1000, 1)
        latency_ms_p95 = round(ds[int(0.95 * len(ds))] * 1000, 1) if len(ds) > 1 else latency_ms_median
        latency_ms_total = round(sum(ds) * 1000, 1)
    else:
        latency_ms_median = latency_ms_p95 = latency_ms_total = 0.0

    n_passed = sum(1 for c in scored if c["metrics"]["score"] == 1.0)

    print(json.dumps({
        "passed": bool(scored) and accuracy >= PASS_THRESHOLD,
        "score": round(accuracy, 3),
        "n_passed": n_passed,
        "n_total": len(cases),
        "n_scored": len(scored),
        "n_skipped_no_gold": len(skipped),
        "threshold": PASS_THRESHOLD,
        "by_category": by_category_pct,
        "latency_ms_median": latency_ms_median,
        "latency_ms_p95": latency_ms_p95,
        "latency_ms_total": latency_ms_total,
        "cost_usd_total": None,
    }))


if __name__ == "__main__":
    main()
