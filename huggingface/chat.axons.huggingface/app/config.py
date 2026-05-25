"""
Axons HuggingFace Plugin - 配置与共享状态

从环境变量读取配置（由 axons 平台注入），定义路径常量和共享可变状态。
"""

import os
import platform
import threading
from pathlib import Path

from huggingface_hub import HfApi

# ============================================================
# 配置：从环境变量读取（由 axons 平台注入）
# ============================================================

AXONS_API_URL = os.environ.get("AXONS_API_URL", "http://127.0.0.1:8080")
AXONS_PLUGIN_TOKEN = os.environ.get("AXONS_PLUGIN_TOKEN", "")
AXONS_PLUGIN_PORT = os.environ.get("AXONS_PLUGIN_PORT", "18080")

# 插件数据目录：优先使用宿主注入的环境变量，回退到默认路径
# AXONS_PLUGIN_ID 由宿主注入（v0.8+），旧版宿主回退到硬编码 ID
AXONS_PLUGIN_ID = os.environ.get("AXONS_PLUGIN_ID", "chat.axons.huggingface")
PLUGIN_DATA_DIR = Path(os.environ.get(
    "AXONS_PLUGIN_DATA_DIR",
    str(Path.home() / ".axons" / "plugins" / "data" / AXONS_PLUGIN_ID),
))
MODELS_DIR = PLUGIN_DATA_DIR / "models"
BIN_DIR = PLUGIN_DATA_DIR / "bin"
METADATA_FILE = PLUGIN_DATA_DIR / "models.json"
DOWNLOAD_HISTORY_FILE = PLUGIN_DATA_DIR / "download_history.json"
MODEL_CONFIGS_FILE = PLUGIN_DATA_DIR / "model_configs.json"

# llama-server 可执行文件名
if platform.system() == "Windows":
    LLAMA_SERVER_BIN = "llama-server.exe"
else:
    LLAMA_SERVER_BIN = "llama-server"

LLAMA_SERVER_PATH = BIN_DIR / LLAMA_SERVER_BIN

# ============================================================
# HuggingFace 配置（镜像站 + Token，由前端设置后传入）
# ============================================================

_HF_CONFIG = {
    "hf_mirror": "",   # 镜像站域名，如 "hf-mirror.com"，空则用默认 hf.co
    "hf_token": "",    # HF Access Token，空则匿名
}


def _get_hf_api() -> HfApi:
    """根据当前配置构建 HfApi 实例"""
    kwargs = {}
    if _HF_CONFIG["hf_mirror"]:
        kwargs["endpoint"] = f"https://{_HF_CONFIG['hf_mirror']}"
    if _HF_CONFIG["hf_token"]:
        kwargs["token"] = _HF_CONFIG["hf_token"]
    return HfApi(**kwargs)


# ============================================================
# 共享可变状态
# ============================================================

# 运行中的模型：model_name → ProcessInfo
_running_processes: dict = {}
_running_lock = threading.Lock()
BASE_PORT = 18081

# 活跃下载任务表
# key: "{repo_id}:{quantization}", value: job dict
_active_downloads: dict = {}
_active_downloads_lock = threading.Lock()


# ============================================================
# 辅助函数
# ============================================================

def _ensure_data_dirs():
    """确保插件数据目录存在"""
    PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)