"""
Axons HuggingFace Plugin - GGUF 量化模式匹配

从 HF repo 文件列表中提取可用量化版本和匹配分片文件。
"""

import re

from app.config import _get_hf_api

# ============================================================
# GGUF 量化模式匹配
# ============================================================

_QUANT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])("
    r"IQ[1-4](?:_[A-Z]+)?"
    r"|Q[2-8](?:_[01KS](?:_[SML])?)?"
    r"|F16|FP16|BF16|F32|FP32"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_SHARD_PATTERN = re.compile(r"[-.]\d{5}-of-\d{5}$", re.IGNORECASE)


def _extract_quantizations(repo_id: str) -> list:
    """从 HF repo 文件列表中提取所有可用量化版本。

    llama.cpp 原生支持分片 GGUF，因此所有量化版本均为可用。
    返回排序后的量化标签列表。
    """
    try:
        api = _get_hf_api()
        files = api.list_repo_files(repo_id)
    except Exception:
        return []

    quants: set = set()
    for f in files:
        if not f.lower().endswith(".gguf"):
            continue
        stem = f[:-5]  # 去掉 .gguf
        # 去掉分片后缀以匹配量化标签
        stem_for_match = _SHARD_PATTERN.sub("", stem)
        for m in _QUANT_PATTERN.finditer(stem_for_match):
            quants.add(m.group(1).upper())

    return sorted(quants)


def _find_gguf_files_for_quant(repo_id: str, quantization: str) -> list:
    """找出 repo 中属于指定量化的所有 GGUF 文件名（含分片）"""
    try:
        api = _get_hf_api()
        files = api.list_repo_files(repo_id)
    except Exception:
        return []

    result = []
    for f in files:
        if not f.lower().endswith(".gguf"):
            continue
        stem = f[:-5]
        stem_for_match = _SHARD_PATTERN.sub("", stem)
        for m in _QUANT_PATTERN.finditer(stem_for_match):
            if m.group(1).upper() == quantization.upper():
                result.append(f)
                break
    return sorted(result)