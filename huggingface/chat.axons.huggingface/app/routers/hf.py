"""
Axons HuggingFace Plugin - HuggingFace 配置与模型搜索路由

/api/hf/config, /api/hf/models
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import _HF_CONFIG, _get_hf_api
from app.gguf import _extract_quantizations

router = APIRouter()


@router.get("/api/hf/config")
async def get_hf_config():
    """获取当前 HF 镜像站和 Token 配置"""
    return _HF_CONFIG


@router.post("/api/hf/config")
async def set_hf_config(body: dict):
    """设置 HF 镜像站和 Token 配置"""
    if "hf_mirror" in body:
        _HF_CONFIG["hf_mirror"] = str(body["hf_mirror"]).rstrip("/")
    if "hf_token" in body:
        _HF_CONFIG["hf_token"] = str(body["hf_token"])
    return {"status": "ok"}


# --- HF 模型搜索 ---


@router.get("/api/hf/models")
async def hf_models(
    keyword: str = "",
    sort: str = "downloads",
    limit: int = 50,
    offset: int = 0,
):
    """搜索 HuggingFace 上的 GGUF 模型"""
    try:
        api = _get_hf_api()
        models = api.list_models(
            filter="gguf",
            search=keyword or None,
            sort=sort,
            limit=limit,
        )
        result = []
        for m in models:
            quants = _extract_quantizations(m.id)
            result.append({
                "id": m.id,
                "author": m.author,
                "downloads": m.downloads,
                "pipeline_tag": m.pipeline_tag,
                "tags": list(m.tags) if m.tags else [],
                "last_modified": m.last_modified.isoformat()
                if m.last_modified
                else None,
                "available_quantizations": quants,
                "url": f"https://huggingface.co/{m.id}",
            })
        return {"models": result, "total": len(result)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to search HuggingFace models: {str(e)}"},
        )