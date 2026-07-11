# AgentHack 矿物鉴定 Agent（Elastic 9.3 + 融合检索 + trapstreet 评测）

> 选型依据见 [RESEARCH-选型报告.md](RESEARCH-选型报告.md)。
> 数据：MineralImage5k-98（Nesteruk et al. 2023, Fersman 矿物博物馆）——仅私用演示，勿再分发图片。
> 嵌入：jina-clip-v2（CC-BY-NC-4.0，演示需标注）。

## 架构

```
矿物图片(5,498张/98种) ──jina-clip-v2──> image_vector ┐
Mindat 属性 + Wikipedia 摘要 ──────────> props_text  ├─> ES minerals-images (RRF: BM25+kNN+过滤)
                                        结构化字段    ┘        minerals-species (ES|QL 工具)
Agent Builder: ES|QL 属性工具 + Workflow/MCP 包 RRF 查询
trapstreet: 闭卷 baseline (swinv2 ~24.5% / 无工具 LLM) vs RAG agent
```

## 运行顺序

```bash
source .venv/bin/activate

# 1. 属性数据（Wikipedia 已抓好；Mindat 需先 export MINDAT_API_KEY=...）
python scripts/fetch_properties.py mindat
python scripts/fetch_properties.py merge

# 2. 嵌入（先计时，再全量约 5,498 张）
python scripts/embed_images.py --dry-run 100
python scripts/embed_images.py

# 3. 入库（先 export ES_URL=... ES_API_KEY=...，Elastic Cloud 部署页生成）
python scripts/index_es.py

# 4. 验证融合检索
python scripts/search_cli.py --text "green banded mineral, green streak, hardness 4" --show-query
python scripts/search_cli.py --image data/images/malachite/validation-00012.jpg

# 5. 评测（见 trap/README.md 的两层设计）
python trap/task/make_cases.py            # trapstreet 公开任务（闭卷 vs RAG）
source .env && .venv/bin/python trap/eval/ablation.py   # RRF 消融（证明融合有用）
```

## 集群方案（2026-07-08 已查证，见下方冒烟测试）

**主选：阿里云 ES 9.3.2（黑客松方案一，预配置 + 专属 Token）——已确认满足 5/6 需求：**
- ✅ RRF retriever（阿里云特性矩阵：8.17 起 GA；官方 RAG 教程直接用 rrf DSL）
- ✅ Agent Builder（阿里云 9.3 发版头条，需 9.3.2+；Kibana → Elasticsearch > Agents）
- ✅ Workflows（9.3 含，但**技术预览且默认隐藏，需在 Kibana 设置手动开启**——刘晓国文章 162767283 有截图）
- ✅ dense_vector/kNN（免费级）
- ✅ Qwen LLM connector：AI Connector → 服务类型 OpenAI → URL `http://{模型服务接入地址}/compatible-mode/v1/chat/completions`，
  Model 用 qwen-plus/qwen3-max（**别用 ops-qwen-turbo**），API key 在 实例控制台 → AI 服务中心 → 模型管理（文章 162036514）
- ❌ **EIS 没有**（Elastic Cloud 专属）→ 预置 `.jina-clip-v2` 端点不存在。影响与替代见下。

**兜底：Elastic Cloud 14 天试用** https://cloud.elastic.co/registration （全功能含 EIS；阿里云现场出问题时 15 分钟内切换）

**开场 5 分钟冒烟测试（三连，任一失败立刻切兜底别调试）：**
1. `GET /_license?accept_enterprise=true`
2. 发一个最小 rrf retriever 查询
3. Kibana 打开 Agent Builder + `POST /api/agent_builder/converse`

**EIS 缺席的影响**：入库嵌入本来就在本地做（不受影响）；查询时嵌入三选一——
(a) 演示 UI 本地嵌入后直连 ES（`search_cli.py` 现成，最稳）；(b) Workflow 加 HTTP 步骤调 Jina API（现场验证）；
(c) 文本语义腿用阿里云 ops-text-embedding-002 semantic_text（注意：与 jina-clip-v2 不同向量空间，不能混用同一字段；
bulk 时 chunk ≤25，阿里云推理端点超 ~32 条会 500——刘晓国文章 162767283 实测）。

## 人工待办（只有你能做）

- [ ] 开通阿里云 ES 试用 https://free.aliyun.com/?productCode=elasticsearch （或等黑客松专属 Token）→ `export ES_URL=... ES_API_KEY=...`
- [x] **Mindat API key** 已配置（.env）
- [ ] （可选）HF token：匿名下载已成功，暂不需要
- [ ] （可选）Jina API key：若走 Workflow 查询时嵌入路线才需要

## 目录

```
scripts/config.py            共享配置 + 类名归一化（credit→creedite 等 10 个）
scripts/fetch_properties.py  Wikipedia/Mindat 属性抓取 + 合并
scripts/embed_images.py      jina-clip-v2 MPS 嵌入 + 缩略图导出
scripts/index_es.py          建索引 + bulk 写入（images/species 双索引）
scripts/search_cli.py        RRF 融合检索 CLI（文/图查询 + 结构化过滤）
trap/task/                   trapstreet 公开任务：case 生成器 + judge.py + reference.md
trap/eval/                   RRF 消融 harness（图像/文本/融合 三路准确率对比）
data/                        parquet(1.17GB val+test) / properties / embeddings / images
```

## 已知边界

- 磁盘仅剩 ~11 GiB：train 分片（2.7 GB）未下载，val+test 5,498 张已够演示
- semantic_text 在 9.3 不支持多模态 → 图像向量手动 dense_vector（已如此实现）
- Agent Builder 无原生 DSL 工具 → 现场用 Workflow 工具包 RRF 查询（配方：CSDN 159643240）
- 13 个非 IMA 变种（agate/amethyst/amber…）无 Mindat 结构化字段，属性以 Wikipedia 为准
