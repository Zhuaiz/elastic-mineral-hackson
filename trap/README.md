# trap/ — 两层评测：证明 RRF，且给出公开可信数字

矿物鉴定 agent 的评测拆成两层，各自证明不同的东西。**别把两者混为一谈**——
这是很多黑客松 demo 翻车的地方（"我接了 RAG，分数变高了" ≠ "我的融合检索有用"）。

## 层一 · `eval/` — RRF 消融实验（技术证据）

**证明的命题：融合检索 > 任何单路检索。**

`ablation.py` 对同一批"没见过的"标本，用三种策略检索已知标本库、投票定种，比准确率：

| 策略 | 用到什么 | 预期 |
|---|---|---|
| `image_only` | 只有照片（jina-clip-v2 图像向量 kNN）| 中等（细粒度矿物视觉歧义大，实测图搜图 top-1 ~25%）|
| `text_only` | 只有野外观察属性（BM25）| 中等（很多矿物共享"硬度7/白条痕/玻璃光泽"）|
| **`rrf_fusion`** | 照片 + 属性 + 硬度过滤（一个 RRF retriever）| **最高** |

只要 `rrf_fusion` 的 top-1 明显高于两条单路，RRF 的价值就用**数字**证明了。
这是"every number on a board is a real run, not a claim"。

跑法（需先 embed + index 完成、ES 就绪）：
```bash
source .env && .venv/bin/python trap/eval/ablation.py --limit 300
```

**为什么消融必须在自己的 harness 里做**：trapstreet 是"闭卷模型 + 固定参考文档 → 作答"
的评测，参考文档在出题时就定死了，内部不做实时检索。所以它**天生无法比较检索策略**。
RRF 是检索策略，必须在能实时切换检索方式的地方（这里）测。

## 层二 · `task/` — trapstreet 公开任务（可信数字）

**证明的命题：接了 Elastic 检索的 agent >> 裸闭卷模型。**

- `task/cases/*.json` — 50 道题，题面是野外可观察属性（晶系/硬度/条痕/颜色/光泽），
  **刻意不含化学式**（化学式≈送答案，会抹平差值）。
- `task/reference.md` — 参考文档，仅取 Wikipedia 摘要（CC BY-SA 4.0，已署名），公开安全。
- `task/judge.py` — 种名归一化后精确匹配（creedite/credit、stibnite/antimonite 等收敛）。

在 trapstreet 上跑两轨：裸模型闭卷 vs 你的 Elastic RAG agent（`/api/agent_builder/converse`），
差值就是系统价值，公开可验证。这给评委一个"真实的、不是嘴说的"头条数字。

生成任务：
```bash
python3 trap/task/make_cases.py
```

## 数据与许可

- 题面属性值是客观事实（硬度、条痕色），不受版权限制。
- `reference.md` 仅用 Wikipedia（CC BY-SA 4.0）。**不含 Mindat 数据**（CC-BY-NC-SA，不可再分发）
  与无授权标本图片——这两者只在本地的层一消融与实时 agent 演示中使用，不进公开仓库。

## 注册到 trapstreet

用本机 `trapstreet-task-add` skill，从本仓库的 `trap/task` 目录 URL 注册。
目录格式（task.json / cases / reference.md / judge.py）在注册前需对照 trapstreet
现有任务（如 financebench）实际布局校准。
