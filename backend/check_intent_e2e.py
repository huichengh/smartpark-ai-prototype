"""端到端意图路由校验：走真实 HTTP，验证「问 A 答 B」不复现。

与 check_intent.py 的分工：
  · check_intent.py      只测纯函数 classify_intent（离线，进 CI）
  · check_intent_e2e.py  走 POST /api/agent/chat，验证认证 → 路由 → 工具 → 落库全链路
                         并断言结论非空、数据来源标注为「演示数据」

用法（服务需先启动）：
    python check_intent_e2e.py
    python check_intent_e2e.py --user tenant1     # 换身份验证数据范围
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010/api"

# (问题, 期望主意图 key, 期望主意图名)
CASES: list[tuple[str, str, str]] = [
    ("本月园区经营情况如何？有哪些风险需要关注？", "operations", "经营分析AI"),
    ("园区整体经营情况怎么样", "operations", "经营分析AI"),
    ("目前园区有哪些需要优先处理的问题？", "operations", "经营分析AI"),
    ("园区现在有什么风险", "operations", "经营分析AI"),
    ("招商线索转化率如何", "leasing", "招商AI"),
    ("A栋改造项目现在进度如何", "project", "AI项目经理"),
    ("当前有哪些项目延期了", "project", "AI项目经理"),
    ("本月收缴率是多少", "finance", "财务AI"),
    ("欠费最多的企业是哪家", "finance", "财务AI"),
    ("园区出租率多少", "space", "空间资产AI"),
    ("有哪些合同快到期了", "contract", "合同AI"),
    ("工单超时率是多少", "property", "物业AI"),
    ("这个月用电量是多少", "energy", "能源AI"),
    ("安全指数多少分", "safety", "安全AI"),
    ("有哪些政策我们可以申报", "policy", "政策AI"),
    ("企业画像分析", "enterprise", "企业画像AI"),
]


def call(method: str, path: str, token: str | None = None,
         body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else None,
        method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Park@2026")
    args = ap.parse_args()

    print("=" * 78)
    print(f"园智汇 · 意图路由端到端校验（账号 {args.user}）")
    print("=" * 78)

    status, tok = call("POST", "/auth/login",
                       body={"username": args.user, "password": args.password})
    if status != 200 or not isinstance(tok, dict):
        print(f"登录失败：{status} {str(tok)[:200]}")
        return 2
    token = tok["access_token"]
    u = tok.get("user") or {}
    print(f"账号：{u.get('real_name')} | 角色：{u.get('role_label')} | 范围：{u.get('data_scope')}\n")

    ok = fail = 0
    for question, expect_key, expect_name in CASES:
        status, res = call("POST", "/agent/chat", token, {"question": question})
        if status != 200 or not isinstance(res, dict):
            fail += 1
            print(f"  [FAIL] 「{question}」HTTP {status} {str(res)[:140]}")
            continue
        got = res.get("intent")
        got_name = res.get("intent_label")
        resp = res.get("response") or {}
        conclusion = (resp.get("结论") or "").strip()
        label = res.get("evidence", {}).get("data_label")
        passed = (got == expect_key and expect_name == got_name
                  and bool(conclusion) and label == "演示数据")
        if passed:
            ok += 1
            print(f"  [OK]   「{question}」\n"
                  f"         → {got_name}({got}) / {res.get('latency_ms')}ms / "
                  f"数据足够={res.get('data_sufficient')} / 来源={label}\n"
                  f"         {conclusion[:88]}")
        else:
            fail += 1
            print(f"  [FAIL] 「{question}」\n"
                  f"         期望 {expect_name}({expect_key})  实际 {got_name}({got})"
                  f"  结论长度={len(conclusion)}  来源={label}")

    print("\n" + "=" * 78)
    print(f"意图路由端到端：{ok} 通过 / {fail} 失败 / 共 {len(CASES)}")
    print("=" * 78)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
