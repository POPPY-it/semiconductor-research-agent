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
    """fastembed + BAAI/bge-small-zh-v1.5（ONNX Runtime，CPU/GPU 可选）。

    模型首次使用自动下载；国内网络请设置 HF_ENDPOINT=https://hf-mirror.com。
    providers：None=CPU（默认）；["CUDAExecutionProvider","CPUExecutionProvider"]=GPU
    （需安装 onnxruntime-gpu，CUDA 不可用时自动回退 CPU）。
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        cache_dir: str | None = None,
        providers: list[str] | None = None,
    ):
        from agent.knowledge.onnx_env import ensure_nvidia_dll_path

        ensure_nvidia_dll_path()  # GPU 需要 nvidia bin 在 PATH（import onnxruntime 之前）
        from fastembed import TextEmbedding  # 延迟导入，保持核心无重依赖

        kwargs: dict = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        if providers:
            kwargs["providers"] = providers
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
