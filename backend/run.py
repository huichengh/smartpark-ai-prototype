"""园智汇后端启动脚本（同时是平台唯一的 HTTP 入口）。

用法：
    python run.py                # 默认 127.0.0.1:8010（与前端 vite 代理一致）
    python run.py --port 8080    # 指定端口
    python run.py --seed         # 启动前强制重建演示数据
    python run.py --reload       # 开发模式热重载

云沙箱部署：
    沙箱只提供一个公网端口，通过环境变量 PORT 注入并要求绑定 0.0.0.0。
    本脚本会自动识别（见 _deploy_ports），部署时无需额外参数，直接
    以 `python run.py` 作为启动命令即可。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402

# 前端 vite（dev 5173 / preview 4173）的 /api 代理固定指向此端口。
# 端口只在 app/core/config.py 里定义一次，避免"改了后端端口忘了改代理"导致的整站 404。
DEFAULT_HOST = settings.BACKEND_HOST
DEFAULT_PORT = settings.BACKEND_PORT


def _deploy_ports(args: argparse.Namespace) -> tuple[str, int]:
    """决定监听地址。

    检测到 PORT 环境变量（部署沙箱注入）时优先采用它，并把默认监听地址从
    127.0.0.1 改为 0.0.0.0（否则反向代理连不上）；否则沿用本地默认值，
    本地开发体验不变。
    """
    env_port = os.getenv("PORT")
    if env_port:
        host = args.host if args.host != DEFAULT_HOST else "0.0.0.0"
        return host, int(env_port)
    return args.host, args.port


def _bootstrap_demo_data() -> None:
    """数据库为空时自动生成演示数据。

    放在启动阶段而不是要求人先记得跑 --seed：clone 下来直接 `python run.py` 就能用；
    云沙箱部署时同样拿不到本地已生成的库，也要在这里自举。
    已有数据时是毫秒级的空操作。
    """
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import Park

    db = SessionLocal()
    try:
        if (db.scalar(select(func.count(Park.id))) or 0) > 0:
            return
    finally:
        db.close()

    print("[seed] 检测到演示数据为空，正在生成（约 40 秒，仅首次）…", flush=True)
    from app.seed import seed_data

    seed_data.main()
    print("[seed] 演示数据生成完成。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="园智汇后端服务")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--seed", action="store_true", help="启动前强制重建演示数据")
    args = parser.parse_args()

    if args.seed:
        print("[1/3] 强制重建演示数据（全部标注 is_demo=True）…", flush=True)
        from app.seed import seed_data

        seed_data.main()
    else:
        print("[1/3] 检查演示数据…", flush=True)
        _bootstrap_demo_data()

    host, port = _deploy_ports(args)
    print(f"[2/3] 启动服务：http://{host}:{port} ｜ 接口文档 /docs")
    print("      前端产物：由本服务托管（frontend/dist 存在时）")
    print("[3/3] 就绪。", flush=True)
    print()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
