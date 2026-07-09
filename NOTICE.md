# 数据来源与许可 / Data Sources & Attribution

本仓库为 Elastic AgentHack（北京，2026-07-11）矿物鉴定 agent 作品。

## 公开包含在本仓库的内容

- **`trap/task/reference.md`** — 描述文字摘自英文维基百科，许可 **CC BY-SA 4.0**
  （https://en.wikipedia.org/ ）。矿物物理属性（莫氏硬度、条痕、晶系等）为客观测量事实，
  不受版权限制。
- **`trap/task/cases/`** — 题面由上述事实属性生成；答案为矿物种名（事实，不可版权）。
- 代码（`scripts/`、`trap/`、`agent-builder/`）为本项目原创，MIT 许可。

## 刻意**不**包含在本仓库的内容（许可所限）

- **Mindat 属性数据**（api.mindat.org，CC-BY-NC-SA 4.0，明确不可再分发）——仅本地用于
  RRF 消融与实时 agent 演示，`data/properties/` 已 gitignore。
- **MineralImage5k 标本图片**（Fersman 矿物博物馆 / Nesteruk et al., *Computers &
  Geosciences* 2023）——上游 GitHub 的 MIT 仅覆盖代码，图片权利未明；仅本地私用演示，
  `data/parquet/`、`data/images/`、`data/embeddings/` 已 gitignore。

## 嵌入模型

- **jina-clip-v2**（jinaai/jina-clip-v2）权重许可 **CC-BY-NC-4.0**，本作品为非商业黑客松
  演示用途；如需商业化须改走 Jina API / EIS 或替换为 Apache-2.0 的 SigLIP2。

## 引用

Nesteruk et al. "MineralImage5k: A benchmark for zero-shot raw mineral visual
recognition and description." *Computers & Geosciences*, 2023.
