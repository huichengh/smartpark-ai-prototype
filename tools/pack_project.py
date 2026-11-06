"""打包项目源码：排除依赖、版本库、构建缓存、二进制工具与 docx。"""
import os
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\84307\WorkBuddy\2026-09-17-00-03-35")
TOP = "园智汇ParkOS-源码包"
OUT = ROOT / "园智汇ParkOS-源码包-20261106.zip"

# 整个目录跳过
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "video",            # video/ 是本地 ffmpeg 二进制，88M，与项目无关
    "dist", ".workbuddy",                # dist 与 backend/webui 重复，webui 保留
}
# 按后缀跳过
SKIP_EXT = {
    ".docx", ".doc", ".pyc", ".pyo", ".log", ".out",
    ".env", ".db-shm", ".db-wal",
}
# 按文件名跳过（.genie 是部署标记，不属于项目内容）
SKIP_NAMES = {".env", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIX = {".genie", ".zip"}


def keep(p: Path) -> bool:
    if p.name in SKIP_NAMES:
        return False
    if p.suffix.lower() in SKIP_EXT:
        return False
    if p.suffix.lower() in SKIP_SUFFIX:
        return False
    return True


EXPLAIN = """园智汇 ParkOS · 源码包
================================

这是「园智汇 · AI 产业园区智慧运营管理平台」的完整源码与演示数据，
不含任何 docx 文档、依赖包（node_modules）与本地工具二进制。

【怎么跑起来】

1. 装依赖
   cd backend
   pip install -r requirements.txt

2. 启动（前后端已打包为一个进程）
   cd backend
   python run.py
   浏览器打开 http://127.0.0.1:8010

   说明：backend/webui 里是已构建的前端产物，所以不需要再跑 npm。
   如果你想改前端：
     cd frontend && npm install && npm run build
     然后把 frontend/dist 覆盖到 backend/webui

3. 演示账号（密码统一 Park@2026）
   admin       集团管理员，全部园区
   p1_manager  园区负责人，单园区视角
   tenant1     企业管理员，入驻企业视角

【目录说明】

backend/app/api/v1     接口层，17 个业务路由模块
backend/app/services   业务引擎（经营测算、CPM、续保风险等纯函数）
backend/app/agent      AI 智能体：意图路由、工具层、编排器
backend/app/models     65 张表的数据模型
backend/data           演示数据库（SQLite，含完整种子数据）
backend/check_*.py     各类校验脚本（字段/路由/权限/工具/意图）
frontend/src           前端源码（React + TS + Tailwind）
docs                   说明文档与演示截图
tools                  开发期用的探针与端到端脚本

【大模型】

默认 rule 模式（纯规则推理，离线可用，结果可复现）。
要接大模型：在 ~/.workbuddy/smartpark.env 里配置 LLM_API_KEY 与 LLM_BASE_URL，
并设置 AGENT_MODE=auto。任何 OpenAI 兼容端点都支持（Ollama / DashScope / DeepSeek）。

注意：不要把 API Key 写进项目目录，部署时会随项目一起上传。
"""


def main() -> None:
    count = 0
    total = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            here = Path(dirpath)
            rel = here.relative_to(ROOT)
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                f = here / name
                if not keep(f) or f.resolve() == OUT.resolve():
                    continue
                arc = Path(TOP) / rel / name
                z.write(f, arc.as_posix())
                count += 1
                total += f.stat().st_size
        z.writestr(f"{TOP}/打包说明.txt", EXPLAIN)

    size = OUT.stat().st_size
    print(f"文件数：{count}（原始 {total/1048576:.1f} MB）")
    print(f"压缩包：{OUT.name}  {size/1048576:.1f} MB")


if __name__ == "__main__":
    main()
