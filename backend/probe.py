"""接口契约探测器 —— 用于在编写前端页面前确认后端真实返回结构。

用法：
    python probe.py /leasing/funnel /contracts/expiring ...
    python probe.py --user p1_manager /dashboard/summary
    python probe.py --post /agent/chat '{"message":"本月园区经营情况如何"}'

设计意图：前端页面里的每一个字典键都必须来自这里打印出的真实结构，
禁止凭记忆书写键名（本会话已因猜错键名返工两次）。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010/api"


def login(username: str = "admin", password: str = "Park@2026") -> str:
    req = urllib.request.Request(
        BASE + "/auth/login",
        method="POST",
        data=json.dumps({"username": username, "password": password}).encode(),
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())["access_token"]


def call(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:400]
    except Exception as e:  # noqa: BLE001
        return "ERR", f"{type(e).__name__}: {e}"


def shape(label: str, obj, depth: int = 0, maxd: int = 2) -> None:
    pad = "  " * depth
    if isinstance(obj, dict):
        print(f"{pad}{label}: dict({len(obj)})")
        if depth >= maxd:
            return
        for k, v in list(obj.items())[:45]:
            if isinstance(v, list):
                print(f"{pad}  {k}: list[{len(v)}]")
                if v and isinstance(v[0], dict):
                    print(f"{pad}    [0] keys: {list(v[0].keys())}")
                    if v[0]:
                        print(f"{pad}    [0] vals: {json.dumps(v[0], ensure_ascii=False, default=str)[:420]}")
            elif isinstance(v, dict):
                print(f"{pad}  {k}: dict keys={list(v.keys())[:32]}")
            else:
                print(f"{pad}  {k}: {type(v).__name__} = {str(v)[:70]}")
    elif isinstance(obj, list):
        print(f"{pad}{label}: list[{len(obj)}]")
        if obj and isinstance(obj[0], dict):
            print(f"{pad}  [0] keys: {list(obj[0].keys())}")
            print(f"{pad}  [0] vals: {json.dumps(obj[0], ensure_ascii=False, default=str)[:420]}")
    else:
        print(f"{pad}{label}: {type(obj).__name__} = {str(obj)[:100]}")


def main() -> None:
    args = sys.argv[1:]
    user = "admin"
    if "--user" in args:
        i = args.index("--user")
        user = args[i + 1]
        del args[i : i + 2]

    token = login(user)
    print(f"# 登录成功 user={user}\n")

    posts: list[tuple[str, dict]] = []
    if "--post" in args:
        i = args.index("--post")
        posts.append((args[i + 1], json.loads(args[i + 2])))
        del args[i : i + 3]

    for path in args:
        status, data = call("GET", path, token)
        print("=" * 78)
        print(f"GET {path}  ->  {status}")
        shape("", data)
        print()

    for path, body in posts:
        status, data = call("POST", path, token, body)
        print("=" * 78)
        print(f"POST {path} {json.dumps(body, ensure_ascii=False)}  ->  {status}")
        shape("", data)
        print()


if __name__ == "__main__":
    main()
