"""重排器抽象：fastembed TextCrossEncoder（bge-reranker-base，ONNX CPU）。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """返回与 texts 对齐的相关性分数（越大越相关）。"""


class FastembedReranker(Reranker):
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        cache_dir: str | None = None,
        providers: list[str] | None = None,
    ):
        from agent.knowledge.onnx_env import ensure_nvidia_dll_path

        ensure_nvidia_dll_path()  # GPU 需要 nvidia bin 在 PATH（import onnxruntime 之前）
        # fastembed 0.8+ 未在顶层导出 reranker，需从子模块导入
        from fastembed.rerank.cross_encoder.text_cross_encoder import TextCrossEncoder

        kwargs = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        if providers:
            kwargs["providers"] = providers
        self._model = TextCrossEncoder(**kwargs)

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        try:
            scores = self._model.rerank(query, texts)
        except TypeError:
            scores = self._model.predict(query, texts)
        return [float(s) for s in scores]
