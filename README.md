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

## 人工待办（只有你能做）

- [ ] **Elastic Cloud 14 天试用注册** https://cloud.elastic.co/registration （无需信用卡）
      建最新版 Hosted 部署 → 拿 ES endpoint URL + API key → `export ES_URL=... ES_API_KEY=...`
      验证：`GET /_license` 应为 trial（全功能，含 RRF/Agent Builder/Workflows/EIS）
- [ ] **Mindat API key** https://www.mindat.org/ 注册 → 个人设置拿 token → `export MINDAT_API_KEY=...`
- [ ] （可选）HF token：本机没有，匿名下载已成功，暂不需要
- [ ] （可选）Jina API key：本地 MPS 嵌入为主，不依赖
- [ ] Kibana 里确认 Agent Builder 可见（ES solution view 默认启用），配 LLM connector（试用含 Elastic Managed LLM）

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
