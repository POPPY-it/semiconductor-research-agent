"""ONNX Runtime GPU 环境注入：把 nvidia wheel 的 bin 目录加入进程 PATH。

onnxruntime-gpu 1.21+ 在 Windows 上加载 CUDA EP 时按 PATH 搜索
cudnn/cudart/nvrtc 等 DLL（add_dll_directory 不够）。nvidia-*-cu12 wheel
把 DLL 装在 site-packages/nvidia/*/bin —— 这里在 import onnxruntime 之前
幂等地把这些目录前置到 PATH，CUDA 可用即自动启用，不可用则回退 CPU。
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

_done = False


def ensure_nvidia_dll_path() -> None:
    """把 site-packages/nvidia/*/bin 前置到 PATH（幂等，仅 Windows 且目录存在时）。"""
    global _done
    if _done or os.name != "nt":
        return
    _done = True
    site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    bins = [d for d in sorted(glob.glob(str(site / "*" / "bin"))) if os.path.isdir(d)]
    if bins:
        os.environ["PATH"] = ";".join(bins + [os.environ.get("PATH", "")])
