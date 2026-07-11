# 演示 Runbook（黑客松当天照着做）

## 零、开场前 10 分钟：把索引和演示跑起来

嵌入 `embeddings.parquet` 一落盘，依次执行：

```bash
cd ~/Documents/claude/es_hackson && source .venv/bin/activate && source .env

# 1) 建图片索引 + 写入 5,498 向量（约 1-2 分钟）
python scripts/index_es.py
# 期望输出: minerals-species 98 docs / minerals-images ~5498 docs

# 2) 快速消融（证明"融合 > 单路"的检索命中率表，不调 LLM，1-2 分钟）
python trap/eval/ablation.py --limit 300
# 记下这张表：image_only / text_only / rrf_fusion 的 top-1，RRF 应最高

# 3) 起演示界面
python demo/app.py
# 浏览器开 http://localhost:8000
```

若 `index_es.py` 报连接错误：确认 `ES_URL` 是 **http://**（不是 https）、`_cat/indices` 能通。

## 一、现场演示动线（3 分钟，按顺序）

### A. 实时"拍照识矿"（视觉高光，先抓眼球）
1. 浏览器已开 `localhost:8000`。**拖入一张标本照片**（从 `data/images/<某种>/` 里挑，或评委手机拍的样本）。
2. 三栏同时出结果：**① 只看图 / ② 只看字 / ③ RRF 融合**。
3. 话术："同一张照片，只靠图像检索会把 agate、chalcedony、jasper（都是隐晶质石英）混在一起——这是真实的视觉歧义。"
4. **在属性框补一句** `white streak; hardness 7; vitreous`，填硬度 `7`，再点鉴定。
5. "加上野外可观察的属性做 BM25、再用硬度做结构化过滤，RRF 一融合，第一名就锁定了。**这就是融合检索的价值——单一模态搜不准，融合才行。**"

### B. Kibana Agent Builder（证明 Elastic 技术深度）
1. 切到 Kibana → Elasticsearch → Agents → **mineralogist** agent。
2. 输入中文：**"我捡到一块绿色带条带的石头，条痕也是绿色，硬度大概4，是什么矿物？"**
3. Agent 自动：翻译术语 → 调 `lookup_mineral_properties`/`filter_minerals_by_properties`（ES|QL 工具）→ 融合检索 → 给出 malachite + 证据 + 备选。
4. 话术："Agent Builder 里我建了 ES|QL 属性工具和融合检索工具，agent 自己决定调哪个。中文提问也行——jina-clip-v2 的文本塔支持 89 种语言。"

### C. trapstreet 公开榜（可信数字，收尾）
1. 打开 trapstreet.run 的矿物任务榜（若已注册）或展示本地 `accuracy_vs_retrieval.json`。
2. 话术："我们没有自说自话。同一套 50 道鉴定题、同一个 judge，检索越强、作答准确率越高——闭卷 X% → 单路 Y% → RRF Z%。每个数字都是真实的一次运行，公开可复现。"

## 二、备好的测试输入（现场不慌）

| 输入 | 从哪来 | 预期 |
|---|---|---|
| 拍照识矿 | `data/images/malachite/`、`azurite/`、`pyrite/` 任选 | RRF 栏第一名 = 该种 |
| 视觉歧义演示 | `data/images/agate/` 或 `chalcedony/` | 只看图会混淆，加属性后 RRF 修正 |
| 中文属性 | Agent Builder 手输 | 正确种名 + 证据 |
| 结构化过滤 | 属性框填硬度，如萤石填 4 | 候选收敛到该硬度带 |

## 三、故障兜底（Plan B）

- **阿里云 ES 挂 / license 异常**：切 Elastic Cloud 14 天试用（全功能含 EIS），`.env` 换 URL/key 即可。
- **演示界面查询嵌入慢/报错**：直接用 `python scripts/search_cli.py --image <path> --show-query`，命令行出结果 + 打印 RRF 查询体（评委也爱看 DSL）。
- **Agent Builder converse 不通**：直接在 Kibana 聊天框演示（浏览器登录不受 OAuth 脚本问题影响）。
- **网络差**：所有嵌入已本地算好，检索只依赖 ES；演示界面纯本地。

## 四、开场 5 分钟冒烟测试（到场先跑，别等演示才发现）
```bash
source .env
curl -s -u "$ES_USER:$ES_PASSWORD" "$ES_URL/_license?accept_enterprise=true"   # 应 enterprise/active
curl -s -u "$ES_USER:$ES_PASSWORD" "$ES_URL/_cat/indices/minerals*?v"           # 两个索引都在
# Kibana 浏览器登录 → Agents → mineralogist 存在
```
