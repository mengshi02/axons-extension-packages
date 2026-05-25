"""
Axons HuggingFace Plugin - 路由注册

汇总所有 API 路由模块，统一注册到 FastAPI app。
"""

from app.routers.engine import router as engine_router
from app.routers.hf import router as hf_router
from app.routers.local_models import router as local_models_router
from app.routers.download import router as download_router
from app.routers.models import router as models_router
from app.routers.cleanup import router as cleanup_router

all_routers = [
    engine_router,
    hf_router,
    local_models_router,
    download_router,
    models_router,
    cleanup_router,
]