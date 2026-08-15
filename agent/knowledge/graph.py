"""轻量知识图谱（GraphRAG-lite）：实体词典抽取 + 共现关系构图 + 邻居扩展检索。

不依赖重型框架：实体词典按领域维护，共现边按文档内同现计数，
查询时通过实体邻居扩展召回，弥补向量 RAG 答不了的"跨文档关联"问题。
"""
from __future__ import annotations

from collections import defaultdict

# 领域实体词典（半导体公司/技术 + 学术通用术语）
DEFAULT_ENTITIES = {
    "companies": [
        "NVIDIA", "英伟达", "TSMC", "台积电", "Intel", "英特尔", "ASML", "AMD",
        "三星", "Samsung", "中芯国际", "SMIC", "SK海力士", "SK hynix", "美光", "Micron",
        "博通", "Broadcom", "高通", "Qualcomm", "苹果", "Apple", "谷歌", "Google", "华为", "Huawei",
    ],
    "tech": [
        "2nm", "3nm", "5nm", "7nm", "EUV", "DUV", "光刻", "先进封装", "CoWoS", "HBM",
        "DRAM", "NAND", "存储", "晶圆代工", "Foundry", "FinFET", "GAA", "Chiplet",
        "EDA", "RISC-V", "GPU", "AI芯片", "算力", "存内计算", "PIM", "3D封装",
    ],
    "academic": [
        "LLM", "大语言模型", "Agent", "智能体", "RAG", "检索增强", "GraphRAG", "知识图谱",
        "多智能体", "multi-agent", "强化学习", "fine-tuning", "微调", "推理", "reasoning",
    ],
}


class EntityExtractor:
    """基于实体词典的确定性 NER（无 LLM，零成本，可解释）。"""

    def __init__(self, entities: dict | None = None):
        self._lookup: dict[str, str] = {}
        for items in (entities or DEFAULT_ENTITIES).values():
            for it in items:
                self._lookup[it.lower()] = it

    def extract(self, text: str) -> list[str]:
        tl = text.lower()
        found = {canon for key, canon in self._lookup.items() if key in tl}
        return sorted(found)


class KnowledgeGraph:
    def __init__(self, extractor: EntityExtractor | None = None):
        self.extractor = extractor or EntityExtractor()
        self.nodes: set[str] = set()
        self.edges: dict[tuple[str, str], int] = defaultdict(int)
        self.entity_docs: dict[str, set[str]] = defaultdict(set)

    def add_document(self, doc_id: str, text: str) -> None:
        ents = self.extractor.extract(text)
        self.nodes.update(ents)
        for e in ents:
            self.entity_docs[e].add(doc_id)
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = sorted((ents[i], ents[j]))
                self.edges[(a, b)] += 1

    def related_entities(self, entity: str, top_k: int = 10) -> list[tuple[str, int]]:
        neighbors: list[tuple[str, int]] = []
        for (a, b), w in self.edges.items():
            if a == entity:
                neighbors.append((b, w))
            elif b == entity:
                neighbors.append((a, w))
        return sorted(neighbors, key=lambda x: -x[1])[:top_k]

    def centrality(self, top_k: int = 20) -> list[tuple[str, int]]:
        deg: dict[str, int] = defaultdict(int)
        for (a, b), w in self.edges.items():
            deg[a] += w
            deg[b] += w
        return sorted(deg.items(), key=lambda x: -x[1])[:top_k]

    def stats(self) -> dict:
        return {"nodes": len(self.nodes), "edges": len(self.edges)}
