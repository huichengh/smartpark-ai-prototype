"""直接调用 agent 工具层，绕过 HTTP，快速定位"工具返回空数据"的原因。

用法：
    python probe_tool.py get_safety_risks
    python probe_tool.py get_policy_matches --user admin
    python probe_tool.py get_space_status --park 1
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from app.agent import tools as T  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import load_auth_context  # noqa: E402
from app.models import User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tool")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--park", type=int, default=None)
    ap.add_argument("--raw", action="store_true", help="打印完整 JSON")
    args = ap.parse_args()

    db = SessionLocal()
    user = db.query(User).filter(User.username == args.user).first()
    if user is None:
        print(f"未找到用户 {args.user}")
        return 2
    auth = load_auth_context(db, user)

    print(f"user={args.user} role={auth.role_label} scope={auth.data_scope} "
          f"visible_parks={auth.visible_park_ids()} park_id={args.park}")
    print(f"_scoped_park_ids = {T._scoped_park_ids(db, auth, args.park)}")

    res = T.call_tool(args.tool, db, auth, park_id=args.park)
    if args.raw:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str)[:6000])
    else:
        data = res.get("data")
        print(f"data_sufficient={res.get('data_sufficient')} missing={res.get('missing_data')}")
        if data is None:
            print("data = None  ← 工具判定数据不足")
        elif isinstance(data, list):
            print(f"data = list[{len(data)}]")
            if data:
                print("first keys:", list(data[0].keys())[:20] if isinstance(data[0], dict) else data[0])
        elif isinstance(data, dict):
            print(f"data keys ({len(data)}): {list(data.keys())[:30]}")
        print("evidence:", json.dumps(res.get("evidence"), ensure_ascii=False, default=str)[:400])
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
