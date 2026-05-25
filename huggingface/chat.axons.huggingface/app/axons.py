"""
Axons HuggingFace Plugin - Axons 平台集成

将运行中的模型注册/注销到 Axons LLM 模型列表，
以便 Axons AI 面板可直接使用本地 llama-server 模型。
"""

import re

import httpx

from app.config import (
    AXONS_API_URL,
    AXONS_PLUGIN_TOKEN,
    _running_lock,
    _running_processes,
)
from app.gguf import _QUANT_PATTERN


def _register_to_axons(model_name: str, base_url: str = None):
    """将运行中的模型注册到 Axons LLM 模型列表

    重要：provider 必须用 "custom"，不能用 "ollama"。
    Axons 只支持 openai/anthropic/custom 三种 provider。
    llama-server 兼容 OpenAI API 规范 (/v1/chat/completions)，走 custom 分支。
    """
    existing = _get_axons_models()

    # 检查是否已注册
    for m in existing:
        if m.get("model") == model_name and m.get("provider") == "custom":
            return  # 已存在

    display_name = _model_display_name(model_name)

    # 如果没有指定 base_url，从运行中的进程获取
    if not base_url:
        with _running_lock:
            info = _running_processes.get(model_name)
            if info and info["process"].poll() is None:
                base_url = f"http://127.0.0.1:{info['port']}/v1"
            else:
                return  # 进程不在运行，无法注册

    body_dict = {
        "name": display_name,
        "provider": "custom",
        "api_key": "llama-server",  # custom 要求非空，llama-server 默认不校验
        "model": model_name,
        "base_url": base_url,
        "multimodal": False,
    }

    with httpx.Client(timeout=10) as client:
        client.post(
            f"{AXONS_API_URL}/api/llm-models",
            json=body_dict,
            headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
        )


def _unregister_from_axons(model_name: str):
    """从 Axons LLM 模型列表中移除"""
    existing = _get_axons_models()
    for m in existing:
        if m.get("model") == model_name and m.get("provider") == "custom":
            try:
                with httpx.Client(timeout=10) as client:
                    client.delete(
                        f"{AXONS_API_URL}/api/llm-models/{m['id']}",
                        headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
                    )
            except Exception:
                pass
            break


def _get_axons_models() -> list:
    """获取 Axons 中已注册的 LLM 模型列表"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{AXONS_API_URL}/api/llm-models",
                headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
            )
            data = resp.json()
        return data.get("models", [])
    except Exception:
        return []


def _model_display_name(model_name: str) -> str:
    """将模型名转换为用户友好的显示名

    Llama-3.2-3B-Instruct-Q4_K_M → Llama-3.2-3B-Instruct (Q4_K_M) [Local]
    """
    # 尝试从量化标签处拆分
    match = _QUANT_PATTERN.search(model_name)
    if match:
        base = model_name[:match.start()].rstrip("-_ ")
        quant = match.group(1).upper()
        name = f"{base} ({quant})"
    else:
        name = model_name
    return f"{name} [Local]"


def _is_our_model(base_url: str) -> bool:
    """判断 base_url 是否指向本插件管理的 llama-server 实例"""
    if not base_url:
        return False
    # 匹配 localhost:{BASE_PORT+} 格式
    return bool(re.search(r"localhost:\d{5}", base_url))