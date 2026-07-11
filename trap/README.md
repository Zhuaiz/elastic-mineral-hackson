# trap/ — 用作答准确率证明 RRF，并给出公开可信数字

矿物鉴定 agent 的评测围绕一个核心命题：**检索越强，模型作答越准；RRF 融合处准确率最高。**
这条曲线爬升本身就是 RRF 有用的证据，而且是用最有说服力的指标（下游作答准确率）说话。

## 一个被修正的认知

> "trapstreet 是闭卷模型评测，天生测不了 RRF" —— **这句话是错的（说太绝了）。**

准确说法：*单个*固定任务、配*单个*固定参考文档，确实没法在内部比较检索策略。
**但**把同一套题在**不同检索配置**下各跑一遍、看 judge 打出的**作答准确率曲线**，
就能干净地证明 RRF —— 因为"给模型的证据质量 → 作答对错"正是 trapstreet 的判分机制在做的事。
检索配置是变量，judge 准确率是因变量，曲线爬升即结论。

## 层一 · `eval/` — 作答准确率 vs 检索强度（主证据）

`accuracy_vs_retrieval.py`：固定题集 + 固定 judge，只变"喂给模型的检索证据"：

| 配置 | 证据来源 | 预期准确率 |
|---|---|---|
| `closed_book` | 无（模型裸答）| 低基线 |
| `bm25` | 只用野外属性文字（BM25 单路）| 中 |
| `image` | 只用标本照片（图像 kNN 单路）| 中 |
| `rrf_w10` → `rrf_w50` → `rrf_w100` | RRF 融合，检索窗口递增（+硬度过滤）| **最高、趋于平台** |

指标 = `task/judge.py` 判的作答准确率（与 trapstreet 完全同一把尺）。
预期出一条"闭卷 → 单路 → RRF"逐级抬升的曲线。**这就是 RRF 有用的数字证据。**

> 诚实提醒：准确率是**爬升到平台**，不是无限涨——上下文喂太多会引入噪声。
> 画成曲线让它自己说话，比断言"越多越好"更可信。

跑法（需 embed + index 完成、ES 就绪；作答自动走 ES `/_inference/completion/qwen-plus`）：
```bash
source .env && .venv/bin/python trap/eval/accuracy_vs_retrieval.py
```
同时会把每配置的作答写到 `trap/solutions/answers/<config>.txt`，供 `submit.py` 上传公开榜。

`ablation.py` 是廉价补充：只测**检索命中率**（图像/文本/RRF 三路 top-1，不调模型），
用来快速确认检索信号存在；作答准确率曲线才是对外呈现的主角。

## 层二 · `task/` — trapstreet 公开榜（可信数字）

同一套题、同一个 judge，把层一的四个配置各作为一个 solution 搬到 trapstreet 公开榜：
- **`closed_book`**（裸模型）/ **`bm25`** / **`image`**（两条单路）/ **`rrf_w100`**（满配 RRF agent）
四个"真实的、不是嘴说的"数字，公开可验证。榜单上 solution 身份 = (repo, commit)，
所以每个配置用一个独立的已推送 commit 提交（见 `solutions/submit.py --solution-commit`）。

- `task/inputs/<id>/question.txt` + `task/expected/<id>/answer.json` — 50 题（trapstreet
  官方格式），题面是野外可观察属性，**刻意不含化学式**（化学式≈送答案）。
- `task/judge.py` — 种名归一化后精确匹配（creedite/credit、stibnite/antimonite 等收敛）。

生成任务：`python3 trap/task/make_cases.py`

## 数据与许可

- 题面属性值是客观事实（硬度、条痕色），不受版权限制。
- `reference.md` 仅用 Wikipedia（CC BY-SA 4.0）。**不含 Mindat 数据**（CC-BY-NC-SA，不可再分发）
  与无授权标本图片——这两者只在本地层一（消融/准确率曲线）与实时 agent 演示中使用。

## 注册到 trapstreet

用本机 `trapstreet-task-add` skill，从本仓库 `trap/task` 目录 URL 注册。
目录格式（task.json / cases / reference.md / judge.py）在注册前需对照 trapstreet
现有任务（如 financebench）实际布局校准。
