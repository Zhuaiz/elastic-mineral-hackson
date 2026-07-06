# AgentHack 矿物分类项目 — HF 数据集与模型选型报告

> 生成于 2026-07-07。12 个并行研究 agent + 逐项对抗验证（所有数字均从 HF API / datasets-server / 官方文档实测核对，非转述）。
> 项目：Elastic Stack 9.3 AI Agent Builder + 融合检索（RRF）+ 矿物分类 + trapstreet 评测。

---

## 一、最终推荐技术栈（一句话版）

**Nech-C/mineralimage5K-98**（图像）+ **Mindat API 属性表 + Wikipedia 摘要**（文本/结构化）+ **jina-clip-v2 本地嵌入**（1024 维，图文同空间，支持中文）+ **ES 单 RRF retriever**（BM25 + kNN + 结构化过滤）+ **Agent Builder（ES|QL 工具 + Workflow/MCP 包 DSL）** + **swinv2-mineral 做闭卷 baseline** + **trapstreet 计分**。

---

## 二、图像数据集（已逐项验证）

### ⭐ 首选：`Nech-C/mineralimage5K-98`
- **18,326 张图，98 个真实矿物种类**（quartz、topaz、hematite、beryl、malachite、azurite…），ClassLabel 齐全
- 分层切分：train 12,828 / val 2,749 / test 2,749（实测，README 卡片略有出入）
- 原生 parquet，**3.91 GB**（10 个分片，实测字节数 3,906,028,015），`load_dataset` 一行加载
- 来源：MineralImage5k 基准（Nesteruk et al., *Computers & Geosciences* 2023，Fersman 矿物博物馆）
- ⚠️ 注意事项：
  - HF 卡片 **license 字段为空**；上游 GitHub MIT 只覆盖代码，博物馆图片权利未明 → 黑客松私用 + 引用论文可以，**不要再分发图片或索引**
  - 类别不均衡：quartz=1,416 → prehnite=13
  - **约 10 个类名需归一化**：labrador→labradorite、nephritis→nephrite、credit→creedite、cobaltin→cobaltite、analcim→analcime 等
  - **description 列中位长度为 0** → BM25 文本必须自己从属性表合成（见第三节）
  - 匿名 HF API 会限流 → 下载前登录并设 `HF_TOKEN`

### 备选（按用途）
| 数据集 | 规模 | 特点 | 用途 |
|---|---|---|---|
| `acmalpha/earth-stones` | 3,219 图 / 87 类 / **57.9 MB** | 每类 37–50 张很均衡；抛光宝石为主；license 标 cc 但上游存疑 | 下载失败时的轻量兜底，几分钟嵌入完 |
| `udayl/rocks` | 10,787 图 / 98 类 / 533 MB | MIT 标签（31% 图片上游无 license）；岩石+矿物混杂需清洗 | 想要"岩石+矿物"混合叙事时 |
| `tedqc/mineral-dataset` | 62,088 图 / **781 真实种名** / 11.3 GB | 无 license 无来源；长尾极重（很多种只有 1–4 张） | 只按 top-100 类流式抽样用 |
| `Quanli1/Minerals_type_images_label` + `_6114` | 43,745 图 / **5,218 种** / 7.4 GB | 每张图配属性句子（成分、硬度、光泽、条痕、晶系）；已验证两库按行对齐、图片字节一致；**属性文本不含种名**，需与 _label 联结 | 想直接拿"图+属性文本"配对语料时 |
| `Rob1221rib/mineralimage5K-98` | 同首选的镜像 | 字节一致 | 主仓库挂掉时的镜像 |

## 三、结构化属性数据（融合检索的文本侧）

### ⭐ 首选：Mindat API（唯一全字段覆盖源）
- OpenAPI schema 实测：`MineralList` 152 个字段，**莫氏硬度（hmin/hmax）、条痕、颜色、光泽、晶系、密度、化学式、短描述全都有**
- `ima=1` 过滤出约 6,100 个 IMA 认可种；`page-size=1500` 约 5 页分页拉完
- 实测 endpoint 在线（无 token 返回 401，符合预期）
- **行动项：现在就去 mindat.org 注册账号拿 API key**（发放通常即时，但别赌活动前夜）
- License CC BY-NC-SA，私用演示 OK，勿再分发

```bash
curl -H "Authorization: Token $MINDAT_KEY" \
  'https://api.mindat.org/v1/geomaterials/?ima=1&fields=id,name,ima_formula,mindat_formula,csystem,hmin,hmax,streak,colour,lustre,lustretype,dmeas,dcalc,diapheny,cleavage,fracturetype,description_short&page-size=1500&format=json'
```

### 配套 / 备份
- **Wikipedia REST summary**（无需 key，CC BY-SA）：`GET https://en.wikipedia.org/api/rest_v1/page/summary/{Name}` — 每种一段高质量描述，做 BM25/semantic_text 长文本腿。98 个常见种全有词条
- **Kaggle `vinven7/comprehensive-database-of-minerals`**（CC0，3,112 种 × 140 列）：唯一完全开放的属性表，缺条痕/光泽/描述，做零 key 兜底
- `evoosa/gemstones`（HF，apache-2.0，487 种 × 160 列）：硬度/折射率是**自由文本**，用前必须数值归一化，且 20–30% 空值
- RRUFF IMA 列表：权威种名脊柱 + 化学式 + 晶系，无物性；Kaggle 镜像 `lsind18/ima-database-of-mineral-properties`（2023-06）

## 四、Embedding 模型

### ⭐ 首选：`jinaai/jina-clip-v2`（本地 MPS）
- 0.9B 参数，1024 维（Matryoshka 可截到 64），**图文同一向量空间** → 一个 dense_vector 字段同时服务 文搜图 / 图搜图 / 文搜文
- **89 语言、中文原生支持**（xlm-roberta 文本塔，README 有中文示例）→ 中文演示查询直接走向量腿
- `SentenceTransformer('jinaai/jina-clip-v2', trust_remote_code=True)`，MPS 可跑
- ⚠️ 权重 license **CC-BY-NC-4.0** — 黑客松演示可用但要在 README 标注；走 Jina API / EIS 则不受权重 license 约束
- ⏱️ MPS 约 2–6 img/s @512px → 18.3k 全量 1–2.5 小时。**建议分层抽样 5–8k（约 20–45 分钟）或提前一晚全量跑；赛前一天先做 100 张计时 dry-run**

### 替代方案
- **EIS 预配置 `.jina-clip-v2`**（文章 162256813 实锤）：`POST _inference/embedding/.jina-clip-v2`，base64 图片直接进，无需本地模型、无需 Jina key —— **全 Elastic 栈叙事加分**；EIS 还有 9.3 GA 的 jina-embeddings-v5-omni（多模态 1024 维）
- **`google/siglip2-so400m-patch14-384`**（apache-2.0，1152 维）：license 最干净的强模型，但多语言明显弱于 jina-clip-v2 —— 中文演示是留在 jina-clip-v2 的又一理由
- CLIP ViT-B/32：只做快速兜底（卡片自认不擅长细粒度分类）
- ❌ jina-embeddings-v4：4B 参数 + Qwen Research License，跳过
- ❌ `wangly1998/Fine-tune_CN_CLIP_mineral`：**死链——仓库里根本没有权重**，从候选清单移除

## 五、闭卷 Baseline（trapstreet 对照组）

### ⭐ `minatosnow/swinv2-base-patch4-window8-256-mineral`
- SwinV2-base，**282 个真实矿物种类**（config.json id2label 实测），apache-2.0（HF API 已验证）
- **top-1 只有 ~24.5%**（vs 随机 0.35%）→ 弱得恰到好处，正是"闭卷 vs Elastic RAG"对比故事里完美的陪衬
- 额外价值：它的 282 类 id2label 可直接收割为物种词表
- 也可加一路"无工具 LLM 闭卷"baseline（trapstreet-eval 本来的玩法）
- 宝石侧备选：`dima806/gemstones_image_detection`（87 宝石类，与矿物分类学不对齐，需人工映射）

## 六、Elasticsearch 9.3 集成要点（全部对官方文档核实）

1. **🚨 License 是最大隐患**：RRF retriever、Agent Builder、Workflows、EIS **全部是 Enterprise 级**（elastic.co/subscriptions 矩阵实测；Basic 只有 standard/kNN/pinned/rescorer retrievers）。缓解：
   - Elastic Cloud 14 天试用 = 全功能 ✅
   - 自部署：`POST /_license/start_trial?acknowledge=true`（30 天全功能）
   - **行动项：本周问主办方阿里云环境到底给什么 license/部署形态**
   - 零 license 兜底：BM25 与 top-level knn 各查一次，客户端代码里做 RRF 融合
2. **RRF retriever 支持 rrf 级 `filter`**（官方文档确认：filter 自动下发到所有子检索器）→ 一个查询搞定 BM25 + kNN + term/range 过滤，正是"融合"的技术核心
3. **semantic_text 在 9.3 只支持纯文本**（多模态 semantic_field 要等 9.5）→ 图像向量必须手动写入 dense_vector；描述文本可选加一条 ELSER semantic_text 第三腿
4. **Agent Builder 没有原生 DSL 工具类型**（只有 ES|QL / Index search / Workflow / MCP 四种，官方文档确认）→ RRF 查询要么包进 Workflow 工具（`elasticsearch.request` step），要么自建 ~50 行 MCP 服务器（顺带解决查询时图片 embedding）
5. Agent Builder 在 ES solution view 默认启用；所有工具自动通过内置 MCP endpoint（`/api/agent_builder/mcp`）对外暴露

### 索引 mapping 骨架
```
species: keyword          name: text
props_text: text          description: semantic_text (可选第三腿, ELSER)
crystal_system/streak/luster/color: keyword
hardness_min/max, specific_gravity: float   (来自 Mindat 数值字段, 不要用 evoosa 自由文本)
image_vector: dense_vector dims=1024 similarity=cosine
image_url: keyword index=false
```

## 七、可近乎照抄的组织者（刘晓国）博客配方

| 文章 ID | 内容 | 用途 |
|---|---|---|
| **161610772** | Jina CLIP v2 + ES 多语言图片搜索完整管线（mapping/嵌入/bulk/kNN 代码全给了） | 图像入库主配方 |
| **162256813** | EIS 预配置 `.jina-clip-v2` 用法 | 全 Elastic 栈嵌入替代 |
| **161995864** | 9.3 向量搜索最佳实践：semantic_text + **RRF retriever 逐字模板** + 重排序 + Agent Builder ES\|QL 工具 | 混合检索主配方 |
| **152114746** | 第一个 Elastic Agent：tools / agents / converse 三大 API + ES\|QL 工具带 ?参数 | Agent 搭建主配方 |
| **159643240** | Workflow 包 Query DSL 当工具（完整 YAML） | RRF 查询暴露给 Agent |
| **153676591** | 内置 MCP server 暴露工具 + MCP/A2A/API 选型指南 | 演示加分项 |
| **159958475** | 组织者本人的多模态 RAG Streamlit repo（github.com/liu-xiao-guo/jina_multimodal_rag，MPS 本地嵌入） | 直接可改的 demo UI |
| **158803972** | Workflow 实现 LLM-as-judge 质量控制 | 与 trapstreet 评测叙事呼应 |
| 155241617 | Agent Builder 工具/agent 的 API 导出与备份 | 赛前导出 JSON，现场分钟级重放 |

## 八、trapstreet 侧

- trapstreet.run 在线（HTTP 200），本机已装 `trapstreet-eval` / `trapstreet-task-add` 两个 skill
- **赛前**：编好矿物 Q&A 任务目录（cases：属性描述→猜种名，或选择题 + 参考文档 + judge.py 按 IMA 标准名归一化判分），用 `/trapstreet-task-add` 注册
- **现场**：跑双轨——闭卷（swinv2 / 无工具 LLM）vs Agent Builder RAG（`POST /api/agent_builder/converse`），judge.py 本地判分，`tp submit` 上榜

## 九、赛前准备清单（按优先级）

- [ ] **今天**：注册 mindat.org 账号拿 API key；确认 HF 账号 + `HF_TOKEN`
- [ ] **本周**：问主办方——阿里云 ES 9.3 是什么 license 级别？Agent Builder/Workflows/EIS 可用吗？（不行就自开 Elastic Cloud 试用）
- [ ] 下载 mineralimage5K-98（3.91 GB）+ earth-stones 兜底（58 MB）
- [ ] 拉 Mindat 属性 dump（约 5 个请求）+ 98 种 Wikipedia 摘要；做 10 个类名归一化映射
- [ ] jina-clip-v2 100 张图计时 dry-run → 决定抽样规模；提前一晚跑全量嵌入
- [ ] 从 parquet 导出缩略图静态目录（demo UI 要能渲染图片）
- [ ] 建好 trapstreet 矿物任务并注册；准备 Agent Builder 工具/agent JSON 导出
- [ ] 演示叙事一句话：地质野外作业 / 矿产勘探 / 宝石鉴定 / 地质教育任选其一说透

## 十、遗留未决事项

1. **主办方部署形态**（决定 license 与 EIS 可用性）— 只能问人
2. MineralImage5k 图片本身的权利状态 — 无解，私用 + 引用 Fersman 博物馆与论文，勿再分发
3. Jina API 免费额度对 1.8 万图是否够 — 定价页 JS 拦截无法核实，**不要依赖**，本地嵌入为主
