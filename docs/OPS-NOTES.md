# 内部运维笔记（集群选型 / 冒烟测试 / 已知边界）

> 从 README 挪来的内部作战记录，评委不用看这页。

## 集群方案（2026-07-08 已查证）

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

**后来实测（2026-07-11）**：集群自带 22 个 `_inference` 端点（`alibabacloud-ai-search` 服务，
含 `qwen-plus` completion），本机 basic auth 直调即可——作答链路不再依赖 Kibana 连接器/浏览器。
Kibana 公网 API 被阿里云 console 认证网关挡住（307），不可直调，但已不需要。

## 环境待办

- [x] 阿里云 ES（公网端点 + basic auth，见 .env）
- [x] **Mindat API key** 已配置（.env）
- [ ] （可选）HF token：匿名下载已成功，暂不需要
- [ ] （可选）Jina API key：若走 Workflow 查询时嵌入路线才需要

## 已知边界

- 磁盘仅剩 ~11 GiB：train 分片（2.7 GB）未下载，val+test 5,498 张已够演示
- semantic_text 在 9.3 不支持多模态 → 图像向量手动 dense_vector（已如此实现）
- Agent Builder 无原生 DSL 工具 → 现场用 Workflow 工具包 RRF 查询（配方：CSDN 159643240）
- 13 个非 IMA 变种（agate/amethyst/amber…）无 Mindat 结构化字段，属性以 Wikipedia 为准
- jina-clip-v2 在 MPS 偶发 NaN → embedder.py 有 CPU 降级守卫（详见该文件 docstring）

## trapstreet 提交契约

见 [trap/solutions/HANDOFF.md](../trap/solutions/HANDOFF.md)。
