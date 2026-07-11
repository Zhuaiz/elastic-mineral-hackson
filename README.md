# 🪨 野外矿物鉴定 Agent — 用 Elastic 融合检索，把作答准确率从 36% 拉到 92%

> **Elastic AgentHack 参赛作品。** 地质队员在野外捡到一块石头：一张照片、几条肉眼观察
> （颜色、条痕、硬度、晶系）。玛瑙/玉髓/碧玉光看照片会混，"硬度 7 + 白条痕 + 玻璃光泽"
> 又被几十种矿物共享——**单一模态谁都不够**。我们用 Elasticsearch 的 `rrf` retriever
> 把图像 kNN、属性 BM25、结构化过滤**在一个查询里融合**，并用两层公开可验证的数字证明它有用。

## 📊 头条数字：公开榜单上的检索消融

同一套 50 题、同一个 judge、同一个 qwen-plus，只变检索配置——四个 solution 同台公开对比：

| 检索配置 | 作答准确率 | vs 闭卷 |
|---|---|---|
| 闭卷（裸 Qwen） | 36.0% | — |
| 图像单路（jina-clip-v2 kNN） | 48.0% | +12 |
| BM25 单路（属性文字） | 56.0% | +20 |
| **RRF 融合（BM25 + 图像 kNN + 硬度过滤）** | **92.0%** | **+56** |

[![trapstreet 公开榜：四个检索配置同台对比](docs/assets/leaderboard.png)](https://trapstreet.run/tasks/mineral-species-id)

▶ **公开榜单（可点进每个 case 看判分）**: [trapstreet.run/tasks/mineral-species-id](https://trapstreet.run/tasks/mineral-species-id)

检索层的独立证据（不调 LLM，2,749 条查询的检索命中率）：

| | image 单路 | text 单路 | **RRF 融合** |
|---|---|---|---|
| top-1 | 20.8% | 23.9% | **53.3%** (+29.4) |
| top-3 | 37.9% | 28.0% | **77.5%** |

两层数字互相印证：**检索越强 → 喂给模型的证据越好 → 作答越准，RRF 处最高。**

## 🏗️ 架构

```
矿物图片(5,498张/98种) ──jina-clip-v2──> image_vector ┐
Mindat 属性 + Wikipedia 摘要 ──────────> props_text  ├─> ES minerals-images（RRF: BM25+kNN+过滤）
                                        结构化字段    ┘    minerals-species（ES|QL 工具）
Agent Builder: mineralogist agent = ES|QL 属性工具 + Workflow 包 RRF 融合查询
作答: ES /_inference/completion/qwen-plus（推理端点，全链路不出 Elastic）
评测: trapstreet 公开任务（trap/task）+ 本地消融 harness（trap/eval）
```

**为什么这是 Elastic 的主场**：
- 一条 `rrf` retriever DSL 同时融合三路信号——不用自己写融合逻辑，不用两套系统
- jina-clip-v2 图文**同一 1024 维空间**：文字线索可以直接 kNN 搜标本照片（跨模态）
- Agent Builder 的 agent 自己决定先按硬度筛还是先按图搜；中文提问也行（jina 文本塔 89 语）
- 连 LLM 作答都走 ES `_inference` 端点——检索、推理、评测一条链路全在 Elastic 生态里

## 🎬 演示

```bash
source .env && .venv/bin/python demo/app.py   # → http://localhost:8000
```

拖一张标本照片进去，三栏并排：只看图 / 只看字 / RRF 融合。
前两栏把玛瑙玉髓碧玉混在一起，融合栏第一名锁定——**这一栏赢，就是 RRF 的价值。**

- 4 分钟讲稿：[docs/PITCH.md](docs/PITCH.md) · 现场手册：[docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md)

## 🚀 复现

```bash
source .venv/bin/activate && source .env    # ES_URL + ES_USER/ES_PASSWORD

python scripts/fetch_properties.py merge    # 1. 属性数据（Wikipedia + Mindat）
python scripts/embed_images.py              # 2. jina-clip-v2 嵌入（5,498 张）
python scripts/index_es.py                  # 3. 建索引 + 入库
python scripts/search_cli.py --text "green banded mineral, hardness 4"   # 4. 验证检索

python trap/eval/ablation.py                          # 检索命中率消融（上表二）
python trap/eval/accuracy_vs_retrieval.py             # 作答准确率四配置（上表一）
python trap/solutions/submit.py rrf_w100 --engine ... # 上传 trapstreet 公开榜
```

## 📁 目录

```
scripts/           数据管线：属性抓取 → 嵌入 → 入库 → 检索 CLI
demo/              三栏对比演示（标准库 http.server，零依赖）
agent-builder/     Agent Builder agent + Workflow RRF 工具定义
trap/task/         trapstreet 公开任务（50 case + judge，官方 traptask 格式）
trap/eval/         两层评测 harness（检索消融 + 作答准确率曲线）
trap/solutions/    四配置作答 + 榜单提交器
docs/              讲稿 / 演示手册 / 内部运维笔记
```

## 📜 数据与许可

- 图片与标签：MineralImage5k-98（Nesteruk et al. 2023，Fersman 矿物博物馆）——**仅本地演示，不再分发**
- 属性：Mindat API（CC-BY-NC-SA，不再分发）+ Wikipedia 摘要（CC BY-SA 4.0，已署名）
- 嵌入：jina-clip-v2（CC-BY-NC-4.0，演示需标注）
- trapstreet 公开任务仅含客观物性数值 + Wikipedia 文本，公开安全

> 集群选型、冒烟测试、已知边界等内部笔记 → [docs/OPS-NOTES.md](docs/OPS-NOTES.md)
> 选型依据 → [RESEARCH-选型报告.md](RESEARCH-选型报告.md)
