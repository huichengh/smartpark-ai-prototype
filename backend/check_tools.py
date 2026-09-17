"""Agent 工具层全量巡检：把 23 个工具全部真跑一遍，暴露"静默失效"。

为什么需要它
    call_tool() 历史上把工具内部异常包成 missing_data，于是
    NameError（SafetyHazard 未导入）、AttributeError（Policy.conditions 是字符串）
    在前端都表现成"数据不足"——一个业务功能整块失效却没有任何报错。
    这个脚本按注册表逐个调用工具并断言 tool_error 不出现，这类问题会立刻暴露。

判定口径
    FAIL  : 工具返回 tool_error=True（内部异常，必须修）
    WARN  : 工具返回 data_sufficient=False（可能合理，如瀑布式项目没有 Sprint，需人工判断）
    OK    : 正常返回数据

用法
    python check_tools.py                # admin 身份（GROUP 全园区）
    python check_tools.py --user p1_manager
    python check_tools.py --verbose
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.agent import tools as T  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import load_auth_context  # noqa: E402
from app.models import Enterprise, Project, User  # noqa: E402

# 需要业务主键才能调用的工具：用真实库里第一条记录注入
NEEDS_PROJECT = {
    "get_project_schedule", "get_project_wbs", "get_project_risks", "get_project_costs",
    "get_project_changes", "get_sprint_status", "generate_project_report",
}
NEEDS_ENTERPRISE = {"get_enterprise_profile"}
# L3 写工具：会在库里留痕，调用后统一 rollback 撤销
WRITE_TOOLS: dict[str, dict] = {
    "create_ai_recommendation": {
        "title": "[巡检] 工具层自检", "summary": "由 check_tools.py 自动生成，随后回滚",
        "category": "经营管理", "agent_key": "operations", "severity": "INFO",
    },
    "create_approval_request": {
        "approval_type": "PROJECT_CHANGE", "title": "[巡检] 工具层自检",
        "content": "由 check_tools.py 自动生成，随后回滚",
    },
}
# data_sufficient=False 属预期业务行为，不计入 WARN
EXPECTED_INSUFFICIENT = {"get_sprint_status"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="admin")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    user = db.query(User).filter(User.username == args.user).first()
    if user is None:
        print(f"未找到用户 {args.user}")
        return 2
    auth = load_auth_context(db, user)

    proj = db.scalar(select(Project).order_by(Project.id))
    ent = db.scalar(select(Enterprise).order_by(Enterprise.id))
    print("=" * 86)
    print(f"Agent 工具层巡检 · 账号 {args.user}（{auth.role_label} / {auth.data_scope}）")
    print(f"样本：project_id={proj.id if proj else None}  enterprise_id={ent.id if ent else None}")
    print("=" * 86)

    fails: list[str] = []
    warns: list[str] = []
    oks = 0

    for name in T.TOOL_REGISTRY:
        kwargs: dict = {}
        if name in NEEDS_PROJECT and proj:
            kwargs["project_id"] = proj.id
        if name in NEEDS_ENTERPRISE and ent:
            kwargs["enterprise_id"] = ent.id
        kwargs.update(WRITE_TOOLS.get(name, {}))

        res = T.call_tool(name, db, auth, **kwargs)
        if res.get("tool_error"):
            fails.append(f"{name}: {res.get('error')}")
            print(f"  [FAIL] {name:26} {res.get('error')}")
            continue

        sufficient = res.get("data_sufficient", True)
        data = res.get("data")
        size = len(data) if isinstance(data, (list, dict)) else ("有" if data else "空")
        ev = res.get("evidence") or {}
        if sufficient:
            oks += 1
            print(f"  [OK]   {name:26} 数据量={size:>4}  "
                  f"表={len(ev.get('tables') or [])} 记录={ev.get('record_count')}")
            if args.verbose:
                print(f"         计算口径：{str(ev.get('formula'))[:110]}")
        else:
            if name in EXPECTED_INSUFFICIENT:
                oks += 1
                print(f"  [OK]   {name:26} data_sufficient=False（预期业务行为）")
            else:
                warns.append(f"{name}: {res.get('missing_data')}")
                print(f"  [WARN] {name:26} data_sufficient=False  {res.get('missing_data')}")

    # 撤销 L3 写工具的副作用
    db.rollback()
    db.close()

    print("\n" + "=" * 86)
    print(f"工具巡检：{oks} 正常 / {len(warns)} 数据不足 / {len(fails)} 内部异常 / "
          f"共 {len(T.TOOL_REGISTRY)}")
    if warns:
        print("\n数据不足（需人工判断是否合理）：")
        for w in warns:
            print("  ·", w)
    if fails:
        print("\n内部异常（必须修复）：")
        for f in fails:
            print("  ·", f)
    print("=" * 86)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
