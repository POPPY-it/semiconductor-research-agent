"""知识层（M2）：向量化、向量库、混合检索。

预研阶段（W2）先用轻量方案跑通链路：
- Embedding: fastembed + BAAI/bge-small-zh-v1.5（ONNX，CPU 快，中文效果好）
- 向量库: Chroma（持久化到本地目录，生产可平滑迁移 pgvector/Milvus）
- 混合检索: BM25（jieba 分词）+ 向量余弦 + RRF 融合
"""
