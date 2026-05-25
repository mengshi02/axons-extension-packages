"""
Axons HuggingFace Plugin - Backend Package

FastAPI 应用定义与路由注册。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import all_routers

# FastAPI 应用
app = FastAPI(title="Axons HuggingFace Plugin")

# CORS 中间件：桌面端直连时必须，Web 端走代理不需要但无害
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册所有路由
for router in all_routers:
    app.include_router(router)