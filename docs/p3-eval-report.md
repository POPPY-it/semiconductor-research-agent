# P3 评测回归：RAG 评测落地与两个方法论发现

## 交付

- `agent/eval.py`：检索指标（Recall@k / MRR / Precision@k，纯计算）+ LLM-as-judge（faithfulness / answer_relevance，用 DeepSeek 打分）
- `data/eval/golden_set.json`：8 条黄金集（问题 + 关键词 + 事实）
- `data/eval/mini_corpus.json` + 内存检索器：CI 自包含（无 DB、无模型下载）
- `scripts/evaluate.py`：`--retrieval-only --mini`（CI）/ `--full`（本地含 LLM）
- CI：test job 新增检索评测回归步骤

## 结果

### mini 语料（干净基线，CI 用）
| 指标 | 值 |
|---|---|
| Recall@5 | 0.875 |
| MRR | 0.938 |
| Precision@5 | 0.375 |

### 真实数据（SEC 财报 + arXiv + 新闻，110+ 篇）
| 指标 | 值 | 解读 |
|---|---|---|
| Recall@5 | 0.127 | ⚠️ 低，见方法论问题 1 |
| MRR | 0.656 | ✅ 排序质量尚可（首位命中率不错） |
| answer_relevance | 1.0 | ✅ 回答都对题 |
| faithfulness | 偏低 | ⚠️ 见方法论问题 2 |

## 两个方法论发现（比指标本身更值钱）

### 问题 1：粗粒度标注把 Recall 压成 0.127
Recall = 命中相关文档 / 全部相关文档。我的"相关"用关键词匹配，导致"台积电"相关文档有几十篇，而 top-5 只能返回 5 篇 → Recall 必然低。
**结论**：Recall 需要**细粒度标注**（精确到"哪一篇财报的第几段"），关键词标注只适合 MRR/Precision。
→ 下一步：黄金集改为精确 doc_id 标注。

### 问题 2：judge 的上下文太窄导致 faithfulness 偏低
faithfulness 用 top-3 检索块作为"上下文"判回答是否被支持，但回答实际用了多工具（财报查询/arXiv/图谱）的更广上下文。
**结论**：应把"回答实际引用的 sources"作为 judge 上下文，而非固定 top-3。
→ 下一步：answer_fn 同时返回 sources，用真实来源做 judge 上下文。

## 面试话术

> "我做了 RAG 评测回归：检索指标 + LLM-as-judge 质量分，黄金集 + CI。跑下来发现**评测集本身是工程的一部分**——粗粒度标注把 Recall 压成 0.127，而 MRR 0.656 才反映真实排序；judge 上下文太窄又低估了 faithfulness。我把这两个方法论坑记进文档，下一步用细粒度标注和真实来源重评。"
