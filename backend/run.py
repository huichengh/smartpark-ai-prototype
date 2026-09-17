"""园智汇后端启动脚本。

用法：
    python run.py                # 默认 127.0.0.1:8010（与前端 vite 代理一致）
    python run.py --port 8080    # 指定端口
    python run.py --seed         # 先重置并生成演示数据，再启动
    python run.py --reload       # 开发模式热重载
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402

# 前端 vite（dev 5173 / preview 4173）的 /api 代理固定指向此端口。
# 端口只在 app/core/config.py 里定义一次，避免"改了后端端口忘了改代理"导致的整站 404。
DEFAULT_HOST = settings.BACKEND_HOST
DEFAULT_PORT = settings.BACKEND_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="园智汇后端服务")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--seed", action="store_true", help="启动前生成演示数据")
    args = parser.parse_args()

    if args.seed:
        print("[1/2] 生成演示数据（演示数据，全部标注 is_demo=True）…")
        from app.seed import seed_data
        seed_data.main()
        print()

    print(f"[2/2] 启动服务：http://{args.host}:{args.port}")
    print(f"      接口文档：http://{args.host}:{args.port}/docs")
    print()

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
