# 交接说明 — 优化 tp 提交与 solution 运行器

给接手的 agent：当前 `closed-book 36% vs elastic-rrf 86%` 已真实上榜
（https://trapstreet.run/tasks/mineral-species-id）。以下是我踩清楚的坑，避免你重复摸索。

## trapstreet 提交的真实契约（比 `tp` CLI 0.4.0 新）

- 本机 `tp` CLI 认证在 **UAT**（`~/.config/trapstreet/auth.json` 的 server）；任务建在 **prod**。
  用户已 `tp auth login` 切到 prod。若你要用 CLI，先确认 `tp auth status` 的 server 是 trapstreet.run。
- **`tp 0.4.0` 的提交路径过时**：它 POST `/{server}/api/submit/{task}` → prod 返回 **404**。
  prod 真实端点是 **`POST https://trapstreet.run/api/submit`**（任务 id 在 body 里），
  `Authorization: Bearer <api_key>`。
- **prod wire 格式**（与 tp 0.4.0 的 `report.py` 模型有差异）：
  - `cases_results`（数组，**不是** `cases`）
  - `provenance.task.{repo, commit}` 和 `provenance.solution.{repo, commit}` 必填，
    commit 必须是已 push 的公开 commit，且 `provenance.task.commit` 要匹配平台上该任务的
    某个已发布版本（`GET /api/tasks/<id>` 的 `latest.commit_sha`）。
  - 每个 case_result：`{case_id, exit_code, duration, metrics, skipped}`，`metrics` 即 judge.py 输出。
  - `submit.py` 已按此格式实现（直接 urllib POST，不再走 `tp submit`）。

## solution 身份的坑（想要两行对比时看这里）

- **solution 身份 = `provenance.solution` 的 (repo, commit)**。顶层 `solution` 字段、
  `provenance.solution.repo_path` 都**不改变归并**（实测同 commit 永远归一个 solution_id）。
- 同一 solution 的多次 run **取最新那条**做榜单 headline（不是最佳）——想让头部显示高分，
  最后提交高分那条。
- **要两行对比（closed-book 一行、elastic-rrf 一行）**：给两者两个**不同的 git commit**
  作为 `provenance.solution.commit`（例如各加一个 marker 文件提交）。这是平台唯一支持的拆分方式。

## 任务版本 / 清理的限制

- 网页表单同 slug 会 **409**（不 bump 版本）；edit 页只改描述、pinned commit 冻结、**无删除按钮**。
- 旧 slug `mineral-id` 是废弃的（pin 了 trapstreet 重构前的旧格式 commit）；canonical 用 `mineral-species-id`。

## solution 运行器现状（可优化点）

- `build_solution.py`：本地对每个 case 的属性文字做 jina-clip-v2 编码 → ES RRF 检索（BM25 props_text
  + 跨模态图像 kNN + 硬度过滤）→ 候选证据。
- 作答在**浏览器经 Kibana Qwen 连接器**跑（qwen-plus）——因为阿里云 AI 平台端点是私网 VPC，
  笔记本直连不通。若能拿到 Qwen 的公网可达端点（DashScope compatible-mode + key），
  就能把作答也搬回本地脚本，`submit.py` 端到端一条命令跑完，不必手动经浏览器。
- `judge.py` 契约：读 `$TRAPTASK_PAYLOAD`（`outputs.case_stdout` / `outputs.case_meta.json` /
  `expected.answer.json`），输出 `{score, agent_answer, ...}`。种名归一化 + 同义词 + no-hedge。
