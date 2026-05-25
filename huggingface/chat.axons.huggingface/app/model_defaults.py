"""
Axons HuggingFace Plugin - 模型兼容性默认配置

不同模型架构对 Metal GPU 的兼容性不同，某些模型在 Metal warmup 时会崩溃。
此模块按模型 family 字段匹配，提供推荐的启动参数默认值。
用户可通过 /api/models/config 自定义覆盖。
"""

import json
from typing import Optional

from app.config import MODEL_CONFIGS_FILE, _ensure_data_dirs
from app.engine import _check_metal_support

# 不同模型架构对 Metal GPU 的兼容性不同，某些模型在 Metal warmup 时会崩溃。
# 此表按模型 family 字段匹配，提供推荐的启动参数默认值。
# 用户可通过 /api/models/config 自定义覆盖。

MODEL_FAMILY_DEFAULTS: dict = {
    # Qwen 系列：Metal warmup 时 ggml_metal_cpy_tensor_async 断言失败，
    # 需要禁用 GPU offload 并跳过 warmup
    "qwen":    {"n_gpu_layers": 0, "no_warmup": True},
    "qwen2":   {"n_gpu_layers": 0, "no_warmup": True},
    "qwen3":   {"n_gpu_layers": 0, "no_warmup": True},
    "qwen2vl": {"n_gpu_layers": 0, "no_warmup": True},
    "qwen3vl": {"n_gpu_layers": 0, "no_warmup": True},
    # 其他模型默认无特殊限制，Metal 可用时全部 offload
}


def _get_model_run_defaults(model_name: str, family: Optional[str]) -> dict:
    """获取模型的推荐启动参数默认值

    优先级：
    1. 用户自定义配置（model_configs.json）
    2. MODEL_FAMILY_DEFAULTS 兼容表
    3. 通用默认值（Metal → -ngl -1，无 Metal → -ngl 0）
    """
    # 1. 用户自定义配置
    configs = _load_model_configs()
    user_config = configs.get(model_name)
    if user_config:
        return user_config

    # 2. 兼容表（按 family 匹配）
    if family:
        family_lower = family.lower()
        for key, defaults in MODEL_FAMILY_DEFAULTS.items():
            if family_lower.startswith(key):
                return dict(defaults)

    # 3. 通用默认值
    has_metal = _check_metal_support()
    if has_metal:
        return {"n_gpu_layers": -1}
    else:
        return {"n_gpu_layers": 0}


def _load_model_configs() -> dict:
    """加载模型配置持久化文件"""
    if MODEL_CONFIGS_FILE.exists():
        try:
            return json.loads(MODEL_CONFIGS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_model_configs(configs: dict) -> None:
    """保存模型配置持久化文件"""
    _ensure_data_dirs()
    MODEL_CONFIGS_FILE.write_text(json.dumps(configs, indent=2, ensure_ascii=False))