"""园智汇 —— 全局配置。

数据库使用 SQLAlchemy URL 配置，默认 SQLite（演示环境），
可通过环境变量 DATABASE_URL 无缝切换到 PostgreSQL。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    PROJECT_NAME: str = "园智汇 SmartPark AI Operations Platform"
    API_V1_PREFIX: str = "/api"
    VERSION: str = "1.0.0"

    # 演示环境默认 SQLite；正式环境设置 DATABASE_URL 指向 PostgreSQL 即可平滑切换
    # 例：postgresql+psycopg://user:pwd@host:5432/smartpark
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'smartpark.db').as_posix()}")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "smartpark-dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12

    # 后端监听地址。前端 vite（dev 5173 / preview 4173）的 /api 代理固定指向此端口，
    # 改端口时请同步修改 frontend/vite.config.ts 的 target，否则整站 /api 会 404。
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8010"))

    # AI Agent 运行模式：rule（本地确定性推理）/ llm（接入大模型）
    AGENT_MODE: str = os.getenv("AGENT_MODE", "rule")

    DEMO_DATA_LABEL: str = "演示数据"
    CORS_ORIGINS: list[str] = ["*"]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
