"""园智汇 · AI 产业园区智慧运营管理平台 —— FastAPI 应用入口。

启动（推荐）：
    cd backend
    python run.py                   # 默认 127.0.0.1:8010
或直接指定：
    python -m uvicorn app.main:app --reload --port 8010
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import traceback
import urllib.parse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.config import BASE_DIR, settings
from app.core.database import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smartpark")

API_PREFIX = settings.API_V1_PREFIX.rstrip("/")

app = FastAPI(
    title="园智汇 · AI 产业园区智慧运营管理平台",
    description=(
        "SmartPark AI Operations Platform\n\n"
        "面向产业园区集团的多租户智慧运营平台，包含数据驾驶舱、空间资产、企业服务、"
        "招商运营、合同财务、项目管理、物业运维、安全管理、审批中心、AI Agent（1 个主 "
        "Agent + 11 个子 Agent）、数据中心、报表中心、日志审计与系统管理。\n\n"
        "**数据说明**：演示环境，全部数据为演示数据（is_demo=True），由数据库实时聚合计算。"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------- CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


# ---------------------------------------------------------------- 中间件
@app.middleware("http")
async def timing_and_log(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("未捕获异常 %s %s", request.method, request.url.path)
        raise
    cost = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{cost:.1f}"
    # HTTP 响应头只能承载 latin-1，中文标签需做百分号编码
    response.headers["X-Data-Label"] = urllib.parse.quote("演示数据")
    if request.url.path.startswith(API_PREFIX) and cost > 800:
        logger.warning("慢请求 %.0fms %s %s", cost, request.method, request.url.path)
    return response


# ---------------------------------------------------------------- 异常处理
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": exc.status_code, "type": "HTTP_ERROR",
                      "message": str(exc.detail)},
            "path": request.url.path,
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errs = []
    for e in exc.errors():
        errs.append({
            "field": ".".join(str(x) for x in e.get("loc", [])),
            "message": e.get("msg"),
            "type": e.get("type"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {"code": 422, "type": "VALIDATION_ERROR",
                      "message": "请求参数校验未通过", "details": errs},
            "path": request.url.path,
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("服务内部错误：%s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {"code": 500, "type": "INTERNAL_ERROR",
                      "message": f"服务内部错误：{exc}"},
            "path": request.url.path,
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        },
    )


# ---------------------------------------------------------------- 路由
app.include_router(api_router, prefix=API_PREFIX)


# ---------------------------------------------------------------- 前端产物托管
# 单端口部署：把前端产物直接挂到后端，`python run.py` 一个进程就能访问完整平台
# （演示、内网交付、云端发布都只需要暴露一个端口）。
#
# 产物候选目录（按顺序取第一个可用的）：
#   1) frontend/dist —— vite 常规构建输出，本地开发 / 预览用
#   2) backend/webui —— 部署时随服务一起打包的副本
# 为什么要第 2 个：云端发布沙箱会排除构建产物目录（dist 属于 build output），
# 只上传源码，于是线上会只剩 API、打不开界面。部署前把 dist 复制到 backend/webui
# 就能随源码一起上传，服务启动即可用，也不必在沙箱里现场 npm build。
# 两个都没有时（未执行 `npx vite build`）自动退回纯 API 模式，/ 返回服务信息 JSON。
_FRONTEND_CANDIDATES = (BASE_DIR.parent / "frontend" / "dist", BASE_DIR / "webui")
DIST_DIR = next((d for d in _FRONTEND_CANDIDATES if (d / "index.html").is_file()),
                _FRONTEND_CANDIDATES[0])
SPA_ENABLED = (DIST_DIR / "index.html").is_file()

if SPA_ENABLED and (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/", tags=["系统"])
def root():
    """服务根：有前端产物时直接返回 SPA，否则返回服务信息 JSON。"""
    if SPA_ENABLED:
        return FileResponse(DIST_DIR / "index.html")
    return {
        "name": "园智汇 · AI 产业园区智慧运营管理平台",
        "name_en": "SmartPark AI Operations Platform",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": API_PREFIX,
        "data_label": "演示数据",
        "status": "running",
    }


@app.get(f"{API_PREFIX}/health", tags=["系统"])
def health() -> dict:
    """健康检查：数据库连通性 + 关键表行数。"""
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import Park, Project, User

    db = SessionLocal()
    try:
        tables = {"users": None, "parks": None, "projects": None}
        try:
            tables["users"] = int(db.scalar(select(func.count(User.id))) or 0)
            tables["parks"] = int(db.scalar(select(func.count(Park.id))) or 0)
            tables["projects"] = int(db.scalar(select(func.count(Project.id))) or 0)
            db_ok = True
            err = None
        except Exception as e:
            db_ok = False
            err = str(e)
        return {
            "status": "healthy" if db_ok else "degraded",
            "database": {"connected": db_ok, "dialect": engine.dialect.name,
                         "rows": tables, "error": err},
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        db.close()


@app.get(f"{API_PREFIX}/meta", tags=["系统"])
def meta() -> dict:
    """平台元信息：模块清单、Agent 清单、输出规范（供前端初始化）。"""
    from app.agent import orchestrator as orch

    sub = []
    for key, cfg in (orch.SUB_AGENTS or {}).items():
        if not isinstance(cfg, dict):
            continue
        sub.append({
            "key": key,
            "name": cfg.get("name"),
            "description": cfg.get("description"),
            "keywords": cfg.get("keywords"),
            "permission_level": cfg.get("permission_level"),
        })

    return {
        "platform": {
            "name": "园智汇",
            "name_en": "SmartPark AI Operations Platform",
            "version": "1.0.0",
            "data_label": "演示数据",
        },
        "main_agent": orch.MAIN_AGENT,
        "sub_agents": sub,
        "sub_agent_count": len(sub),
        "output_sections": [
            "结论", "关键数据", "原因分析", "建议措施",
            "影响范围", "风险", "责任部门/角色", "决策状态",
        ],
        "ai_permission_levels": [
            {"level": "L1", "name": "信息查询", "rule": "AI 可直接回答"},
            {"level": "L2", "name": "分析与建议", "rule": "AI 给建议，人工决定是否采纳"},
            {"level": "L3", "name": "高影响动作", "rule": "AI 只生成审批请求，必须人工审批，绝不自行执行"},
        ],
        "data_scope_levels": ["GROUP", "PARK", "DEPARTMENT", "PROJECT", "ENTERPRISE", "SELF"],
        "runtime": _runtime_probe(),
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
    }


# SPA history 路由回落：必须注册在**所有** API 路由之后，否则会抢走接口请求。
# 只接管非 /api、非文档路径；/api 下的未知路径仍返回 404 JSON，接口语义不变。
if SPA_ENABLED:

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path.split("?")[0] in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (DIST_DIR / full_path).resolve()
        # 静态文件（favicon 等）直接返回，其余一律回落 index.html
        if full_path and candidate.is_file() and str(candidate).startswith(str(DIST_DIR.resolve())):
            return FileResponse(candidate)
        return FileResponse(DIST_DIR / "index.html")


@app.on_event("startup")
def on_startup() -> None:
    logger.info("=" * 74)
    logger.info("园智汇 · AI 产业园区智慧运营管理平台 启动中…")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("数据库就绪：%s", engine.url)
    except Exception as e:
        logger.error("数据库初始化失败：%s", e)

    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import Park
    db = SessionLocal()
    try:
        n = db.scalar(select(func.count(Park.id))) or 0
        if n == 0:
            logger.warning("检测到园区数据为空，请先执行：python -m app.seed.seed_data")
        else:
            logger.info("检测到 %d 个园区，演示数据已就绪（标注：演示数据）", n)
    except Exception as e:
        logger.warning("数据自检跳过：%s", e)
    finally:
        db.close()

    logger.info("接口文档：http://%s:%s/docs", settings.BACKEND_HOST, settings.BACKEND_PORT)
    logger.info("运行时自检：%s", _runtime_probe())
    logger.info("=" * 74)


def _runtime_probe() -> str:
    """打印关键可选依赖的可用情况。

    认证/密码模块都有"缺依赖时退化到纯标准库"的兜底实现，但两条路径产出的
    令牌格式不同。部署环境装不到可选依赖时会出现"签发能用、校验失败"的怪象，
    启动时把实际生效的实现打出来，能一眼看出环境差异。
    """
    from app.core import security as sec

    parts = [
        f"jwt={'python-jose' if sec._HAS_JOSE else '内置 HMAC（退化）'}",
        f"password={'bcrypt' if sec._HAS_BCRYPT else 'PBKDF2（退化）'}",
    ]
    try:
        import jose

        parts.append(f"python-jose={getattr(jose, '__version__', 'unknown')}")
    except Exception:  # noqa: BLE001
        parts.append("python-jose=未安装")
    return " | ".join(parts)


@app.on_event("shutdown")
def on_shutdown() -> None:
    logger.info("园智汇平台已停止服务")
