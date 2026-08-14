"""Embedding 抽象：预研用 Fastembed（bge-small-zh-v1.5），生产可切换 bge-m3 API。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与输入一一对应的向量。"""

    @property
    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""


class FastembedEmbedder(Embedder):
    """fastembed + BAAI/bge-small-zh-v1.5（ONNX runtime，CPU 即可）。

    模型首次使用自动下载；国内网络请设置 HF_ENDPOINT=https://hf-mirror.com。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", cache_dir: str | None = None):
        from fastembed import TextEmbedding  # 延迟导入，保持核心无重依赖

        kwargs = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        self._model = TextEmbedding(**kwargs)
        self._dim: int | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        # .tolist() 得到原生 Python float，chromadb 类型校验才接受
        return [v.tolist() for v in self._model.embed(texts)]

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self.embed(["测维度"])[0])
        return self._dim
