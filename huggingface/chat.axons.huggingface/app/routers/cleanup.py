"""
Axons HuggingFace Plugin - 清理端点

/cleanup - 插件停止前由平台调用
"""

import httpx
from fastapi import APIRouter

from app.config import AXONS_API_URL, AXONS_PLUGIN_TOKEN
from app.engine import _stop_all_processes
from app.axons import _get_axons_models, _is_our_model

router = APIRouter()


@router.post("/cleanup")
async def cleanup():
    """插件停止前由平台调用，清理通过 Axons API 注册的副作用数据。

    停止所有运行中的 llama-server 进程，
    并将所有本插件注册到 Axons 的模型取消注册。
    平台 5s 超时，此端点必须快速完成。
    """
    try:
        # 停止所有进程
        _stop_all_processes()

        # 清理 Axons 注册
        existing = _get_axons_models()
        with httpx.Client(timeout=3) as client:
            for m in existing:
                if m.get("provider") == "custom" and m.get("model"):
                    base_url = m.get("base_url", "")
                    # 清理本插件注册的模型（端口范围在 BASE_PORT 以上）
                    if _is_our_model(base_url):
                        try:
                            client.delete(
                                f"{AXONS_API_URL}/api/llm-models/{m['id']}",
                                headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
                            )
                        except Exception:
                            pass
        return {"status": "cleaned"}
    except Exception as e:
        return {"status": "partial", "error": str(e)}