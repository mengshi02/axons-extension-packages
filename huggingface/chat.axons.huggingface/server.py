"""
Axons HuggingFace Plugin - Backend Server Entry Point

仅作为启动入口，创建 FastAPI app 并启动 uvicorn。
所有业务逻辑已拆分到 app/ 包下。
"""

import sys

from app import app
from app.config import AXONS_PLUGIN_PORT


def read_port_from_stdin() -> int:
    """从 stdin 读取 axons 分配的端口号（stdin 端口注入协议）"""
    try:
        line = sys.stdin.readline().strip()
        if line.startswith("PORT:"):
            return int(line[5:])
    except Exception:
        pass
    # fallback: 从环境变量读取
    return int(AXONS_PLUGIN_PORT)


if __name__ == "__main__":
    import uvicorn

    port = read_port_from_stdin()
    uvicorn.run(app, host="127.0.0.1", port=port)