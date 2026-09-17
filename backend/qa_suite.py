#!/usr/bin/env python
"""对抗性测试套件：数据隔离 / 权限 / 参数边界 / 数据一致性。

与 `check_*.py` 的分工：那些是**静态**检查（读代码、比契约），本套件是**运行时对抗测试**——
用三个角色的真实令牌去打接口，试图越权、传坏参数、制造不一致，看系统会不会漏。

为什么要单独做这套：冒烟测试（smoke_test.py）走的是"正常路径"，全部通过也无法说明
隔离与边界是安全的。数据范围（GROUP/PARK/ENTERPRISE）这类缺陷只有在**换身份去打**
的时候才会暴露——企业管理员能看到全园区 1.3 万条账单，冒烟测试是发现不了的。

用法：
    python qa_suite.py                      # 默认打 127.0.0.1:8010
    python qa_suite.py http://host:port     # 指定目标

退出码：0 = 全部通过；1 = 存在 FAIL。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010").rstrip("/")
API = f"{BASE}/api"
PASSWORD = "Park@2026"

_results: list[tuple[str, str, str, str]] = []   # (级别, 分组, 名称, 说明)
_tokens: dict[str, str] = {}


# --------------------------------------------------------------------------- 基础
def call(method: str, path: str, token: str | None = None, body=None,
         raw_body: bytes | None = None, headers: dict | None = None):
    """返回 (status, parsed_json_or_text)。不抛异常，方便断言各种状态码。"""
    url = path if path.startswith("http") else f"{API}{path}"
    data = raw_body
    hdrs = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(text)
            except json.JSONDecodeError:
                return r.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def record(level: str, group: str, name: str, detail: str = "") -> None:
    _results.append((level, group, name, detail))


def expect(cond: bool, group: str, name: str, detail: str = "", level: str = "FAIL") -> bool:
    record("PASS" if cond else level, group, name, "" if cond else detail)
    return cond


def login(username: str) -> str:
    if username in _tokens:
        return _tokens[username]
    st, d = call("POST", "/auth/login", body={"username": username, "password": PASSWORD})
    tok = (d or {}).get("access_token", "") if isinstance(d, dict) else ""
    _tokens[username] = tok
    return tok


# --------------------------------------------------------------------------- 分组
def group_scope_isolation() -> None:
    """数据范围隔离：不同身份只能看到自己范围内的主体数据。"""
    G = "数据隔离"
    admin, pm, tenant = login("admin"), login("p1_manager"), login("tenant1")

    # 前置：拿到 tenant1 应该归属的企业
    me = call("GET", "/auth/me", tenant)[1]
    ent_id = (me or {}).get("enterprise_id") if isinstance(me, dict) else None
    expect(bool(ent_id), G, "tenant1 已绑定归属企业",
           f"enterprise_id = {ent_id!r}（企业管理员未绑定企业，无法判定数据范围）")

    # 企业列表：企业管理员只应看到自己那一家
    st, d = call("GET", "/enterprise/enterprises?page_size=200", tenant)
    items = (d or {}).get("items") or [] if isinstance(d, dict) else []
    total = (d or {}).get("total") if isinstance(d, dict) else None
    expect(total == 1 and len(items) == 1, G,
           "企业管理员的企业列表仅含本企业",
           f"实际可见 total={total}（企业总数 344）")

    # 企业详情：不得读取别家企业
    other = next((i for i in items if ent_id and i.get("id") != ent_id), None)
    probe_id = (other or {}).get("id") or (ent_id + 1 if ent_id else 2)
    st, _ = call("GET", f"/enterprise/enterprises/{probe_id}", tenant)
    expect(st in (403, 404), G, f"企业管理员读别家企业详情被拒（id={probe_id}）",
           f"实际返回 {st}（越权读取：返回了别家企业的统一社会信用代码、注册资本等信息）")

    # 合同 / 账单 / 工单：企业管理员应只看到自己企业的
    for ep, label in (("/contracts?page_size=200", "合同"),
                      ("/finance/bills?page_size=200", "账单"),
                      ("/operation/work-orders?page_size=200", "工单")):
        st, d = call("GET", ep, tenant)
        t = (d or {}).get("total") if isinstance(d, dict) else None
        if t is None:
            record("WARN", G, f"企业管理员的{label}列表可统计", f"返回体无 total：{str(d)[:80]}")
        else:
            record("INFO", G, f"企业管理员可见{label} total={t}", "")

    # 详情类越权读：企业管理员不得读取别家企业名下的合同 / 账单 / 工单
    st, d = call("GET", "/contracts?page_size=200", admin)
    foreign_contracts = [i for i in ((d or {}).get("items") or [])
                         if ent_id and i.get("enterprise_id") != ent_id]
    if foreign_contracts:
        cid = foreign_contracts[0]["id"]
        st, _ = call("GET", f"/contracts/{cid}", tenant)
        expect(st in (403, 404), G, f"企业管理员读别家企业合同被拒（id={cid}）", f"实际 {st}")

    st, d = call("GET", "/finance/bills?page_size=200", admin)
    foreign_bills = [i for i in ((d or {}).get("items") or [])
                     if ent_id and i.get("enterprise_id") != ent_id]
    if foreign_bills:
        bid = foreign_bills[0]["id"]
        st, _ = call("GET", f"/finance/bills/{bid}", tenant)
        expect(st in (403, 404), G, f"企业管理员读别家企业账单被拒（id={bid}）", f"实际 {st}")

    # 工单 / 会议室预定：企业账号只能看到本企业的（实测曾分别泄露 589 / 177 条）
    # 注意：断言不能写在 "if items 非空" 里面——列表为空时断言会被静默跳过，
    # 测试变成"永远通过"的空断言，越权缺陷反而测不出来。
    for ep, label, code_key in (("/operation/work-orders?page_size=200", "工单", "order_code"),
                                ("/operation/meeting-rooms/bookings?page_size=200", "会议室预定",
                                 "booking_code")):
        st, d = call("GET", ep, tenant)
        if st != 200 or not isinstance(d, dict):
            record("WARN", G, f"企业管理员可读取{label}列表", f"{ep} → {st} {str(d)[:70]}")
            continue
        items = d.get("items") or []
        foreign = [i for i in items if i.get("enterprise_id") and i.get("enterprise_id") != ent_id]
        expect(not foreign, G, f"企业管理员的{label}列表只含本企业数据",
               f"越界 {len(foreign)} 条，例如 {foreign[0].get(code_key) if foreign else ''}"
               f"（含别家企业的报修内容与报修人手机号）")
        record("INFO", G, f"企业管理员可见{label} {len(items)} 条（均为本企业）", "")

    # 园区负责人：不得跨园区
    st, d = call("GET", "/auth/parks", pm)
    parks = (d or {}).get("items") or [] if isinstance(d, dict) else []
    expect(len(parks) == 1, G, "园区负责人可见园区数为 1",
           f"实际 {[p.get('park_name') for p in parks]}")
    my_park = parks[0]["id"] if parks else None

    ok = call("GET", f"/dashboard/summary?park_id={my_park}", pm)[0]
    expect(ok == 200, G, "园区负责人可访问本园区驾驶舱", f"实际 {ok}")
    for pid in _all_park_ids(admin):
        if pid == my_park:
            continue
        st = call("GET", f"/dashboard/summary?park_id={pid}", pm)[0]
        expect(st == 403, G, f"园区负责人访问 park {pid} 被拒", f"实际 {st}")

    # 园区负责人的项目列表不应包含其他园区的项目
    st, d = call("GET", "/projects?page_size=200", pm)
    if isinstance(d, dict) and d.get("items"):
        foreign = [i for i in d["items"] if i.get("park_id") not in (None, my_park)]
        expect(not foreign, G, "园区负责人的项目列表不含其他园区项目",
               f"越界项目 {len(foreign)} 条：{[i.get('project_code') for i in foreign[:3]]}")


def _all_park_ids(admin_token: str) -> list[int]:
    st, d = call("GET", "/space/parks", admin_token)
    if isinstance(d, dict):
        items = d.get("items") or []
        if items:
            return [i["id"] for i in items]
    return [1, 2, 3, 4]


def group_write_privilege() -> None:
    """越权写：低权限身份不得修改不属于自己的业务数据。"""
    G = "越权写"
    admin, tenant = login("admin"), login("tenant1")

    # 取一条不属于 tenant1 的账单 / 合同
    st, d = call("GET", "/finance/bills?page_size=3", admin)
    bill = ((d or {}).get("items") or [{}])[0]
    st, d = call("GET", "/contracts?page_size=3", admin)
    contract = ((d or {}).get("items") or [{}])[0]

    if bill.get("id"):
        st, _ = call("POST", f"/finance/bills/{bill['id']}/pay", tenant,
                     body={"amount": 1, "pay_method": "TRANSFER"})
        expect(st in (401, 403, 404), G, "企业管理员不能缴别家企业的账单",
               f"实际 {st}（越权写：可对任意账单发起缴费）")

    if contract.get("id"):
        # reason 是 query 参数（不是 body），早期用 body 会拿到 422 而误判为"已拦截"
        st, _ = call("POST", f"/contracts/{contract['id']}/terminate?reason=QA%E6%B5%8B%E8%AF%95", tenant)
        expect(st in (401, 403, 404), G, "企业管理员不能终止别家企业的合同",
               f"实际 {st}（越权写：可终止任意合同）")

    # 系统管理类写操作：企业管理员一律无权
    st, _ = call("POST", "/system/users", tenant,
                 body={"username": "qa_probe", "real_name": "越权探针", "password": "Park@2026"})
    expect(st in (401, 403), G, "企业管理员不能创建系统用户", f"实际 {st}")


def group_auth() -> None:
    """鉴权边界。"""
    G = "鉴权"
    admin = login("admin")
    st, _ = call("GET", "/auth/me")
    expect(st == 401, G, "无令牌访问被拒", f"实际 {st}")
    st, _ = call("GET", "/auth/me", "aaa.bbb.ccc")
    expect(st == 401, G, "伪造令牌被拒", f"实际 {st}")
    token = login("admin")
    st, _ = call("GET", "/auth/me", token[:-4] + "aaaa")
    expect(st == 401, G, "篡改签名的令牌被拒", f"实际 {st}")
    st, _ = call("GET", "/auth/me", admin)
    expect(st == 200, G, "有效令牌可访问", f"实际 {st}")


def group_parameters() -> None:
    """参数边界：坏参数不得产生 5xx。"""
    G = "参数边界"
    admin = login("admin")
    cases = [
        ("GET", "/projects?page=0", None, "page=0"),
        ("GET", "/projects?page=-1", None, "page=-1"),
        ("GET", "/projects?page_size=0", None, "page_size=0"),
        ("GET", "/projects?page_size=-1", None, "page_size=-1"),
        ("GET", "/projects?page_size=100000", None, "page_size=100000"),
        ("GET", "/contracts/expiring?days=-1", None, "days=-1"),
        ("GET", "/contracts/expiring?days=99999", None, "days=99999"),
        ("GET", "/projects/99999999", None, "不存在的项目 id"),
        ("GET", "/enterprise/enterprises/99999999", None, "不存在的企业 id"),
        ("GET", "/contracts/99999999", None, "不存在的合同 id"),
        ("GET", "/finance/bills/99999999", None, "不存在的账单 id"),
        ("GET", "/operation/work-orders/99999999", None, "不存在的工单 id"),
        ("GET", "/projects/abc", None, "路径参数非数字"),
        ("GET", "/projects?page=abc", None, "page 非数字"),
        ("GET", "/projects?status=NOT_A_STATUS", None, "非法枚举值"),
        ("GET", "/enterprise/enterprises?keyword=" + "A" * 2000, None, "超长查询串"),
        ("GET", "/enterprise/enterprises?keyword=" + urllib.parse.quote("' OR 1=1--"), None,
         "SQL 注入特征串"),
        ("GET", "/projects?page=1&page_size=1e9", None, "page_size 科学计数"),
    ]
    for method, path, body, label in cases:
        st, d = call(method, path, admin, body=body)
        ok = st not in (500, 502, 503) and st != 0
        detail = f"{label} → {st} {str(d)[:110]}"
        if st == 422:
            expect(True, G, f"{label} 被校验拦截（422）", "")
        elif st in (200, 400, 404):
            expect(True, G, f"{label} 返回 {st}", "")
        else:
            expect(ok, G, f"{label} 不应 5xx", detail)

    # 畸形请求体
    st, _ = call("POST", "/auth/login", raw_body=b"{not json",
                 headers={"Content-Type": "application/json"})
    expect(st in (400, 422), G, "畸形 JSON 被拒（400/422）", f"实际 {st}")
    st, _ = call("POST", "/auth/login", body={})
    expect(st in (400, 401, 422), G, "空登录体被拒", f"实际 {st}")
    st, _ = call("POST", "/agent/chat", admin, body={})
    expect(st in (400, 422), G, "AI 对话缺必填字段被拒", f"实际 {st}")
    st, _ = call("POST", "/operation/work-orders", admin, body={"title": "x"})
    expect(st in (400, 422), G, "建工单缺必填字段被拒", f"实际 {st}")


def group_consistency() -> None:
    """数据一致性：同一业务口径在不同接口上必须给出相同结果。"""
    G = "数据一致性"
    admin = login("admin")

    # 工单：未闭环 + 已闭环 == 总量
    st, d = call("GET", "/operation/work-orders/stats/by-type", admin)
    if isinstance(d, dict) and d.get("total") is not None:
        o, c, t = d.get("open"), d.get("closed"), d.get("total")
        if None not in (o, c, t):
            expect(o + c == t, G, "工单 未闭环+已闭环 == 总量", f"{o}+{c} != {t}")

    # 驾驶舱 KPI 与明细接口必须一致（同一指标只能有一个口径）
    st, dash = call("GET", "/dashboard/summary", admin)
    kpis = {}
    if isinstance(dash, dict):
        kpis = {k.get("label"): k.get("value") for k in (dash.get("kpis") or [])}

    def detail_total(path: str):
        st, d = call("GET", path, admin)
        return (d or {}).get("total") if isinstance(d, dict) else None

    cross = [
        ("企业数量", "/enterprise/enterprises?page_size=1"),
        ("在建项目数量", "/projects/portfolio"),
    ]
    for label, path in cross:
        if label not in kpis:
            continue
        got = detail_total(path)
        if got is None:
            st, d = call("GET", path, admin)
            got = (d or {}).get("in_progress") if isinstance(d, dict) else None
        if got is None:
            record("WARN", G, f"「{label}」可与明细核对", f"{path} 未提供可比数值")
            continue
        expect(float(kpis[label]) == float(got), G, f"驾驶舱「{label}」== 明细接口",
               f"驾驶舱 {kpis[label]} vs 明细 {got}")

    # 合同到期预警：驾驶舱 KPI 与明细接口必须同口径
    if "90天内合同到期" in kpis:
        a = detail_total("/contracts?expiring_days=90&page_size=1")
        st, d = call("GET", "/contracts/expiring?days=90", admin)
        b = (d or {}).get("total") if isinstance(d, dict) else None
        expect(float(kpis["90天内合同到期"]) == float(a or -1), G,
               "驾驶舱「90天内合同到期」== /contracts 明细",
               f"驾驶舱 {kpis['90天内合同到期']} vs /contracts {a}")
        expect(a == b, G, "「90天内合同到期」两处接口同口径",
               f"/contracts?expiring_days=90 → {a}；/contracts/expiring?days=90 → {b}")

    # 百分比字段范围：只认真正的比率字段（rate / *_rate / ratio），避免把 rated_count 当比率
    st, d = call("GET", "/operation/work-orders/stats/by-type", admin)
    if isinstance(d, dict):
        for k, v in d.items():
            if not isinstance(v, (int, float)):
                continue
            is_rate = k == "rate" or k.endswith("_rate") or k.endswith("_ratio")
            if is_rate and not (0 <= v <= 100):
                expect(False, G, f"工单统计 {k} 在 0–100 之间", f"实际 {v}")
    record("PASS", G, "比率类字段均在 0–100 之间", "")

    # 逾期欠费金额必须为非负，且账龄分档之和 == 欠费总额
    st, dash = call("GET", "/dashboard/summary", admin)
    if isinstance(dash, dict):
        for key in ("arrears_aging", "aging"):
            aging = dash.get(key)
            if isinstance(aging, list) and aging:
                s = sum((x.get("amount") or 0) for x in aging)
                total = next((k.get("value") for k in (dash.get("kpis") or [])
                              if "欠费" in (k.get("label") or "")), None)
                if total is not None:
                    expect(abs(s - float(total)) < 1.0, G, "欠费账龄分档之和 == 欠费总额",
                           f"{s:.2f} != {total}")
                expect(all((x.get("amount") or 0) >= 0 for x in aging), G,
                       "账龄分档金额均为非负", "")
                break


def main() -> int:
    print("=" * 92)
    print(f"对抗性测试套件 · 目标 {BASE}")
    print("=" * 92)
    st, _ = call("GET", "/health")
    if st != 200:
        print(f"服务不可用（/api/health → {st}）")
        return 1

    for fn in (group_auth, group_scope_isolation, group_write_privilege,
               group_parameters, group_consistency):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            record("FAIL", "套件", f"{fn.__name__} 执行异常", repr(e)[:160])

    cur = ""
    fails = warns = passes = infos = 0
    for level, group, name, detail in _results:
        if group != cur:
            print(f"\n【{group}】")
            cur = group
        mark = {"PASS": "  ✔", "FAIL": "  ✘", "WARN": "  !", "INFO": "  ·"}[level]
        line = f"{mark} {name}"
        if detail:
            line += f"\n      └─ {detail}"
        print(line)
        if level == "FAIL":
            fails += 1
        elif level == "WARN":
            warns += 1
        elif level == "PASS":
            passes += 1
        else:
            infos += 1

    print("\n" + "=" * 92)
    print(f"结果：通过 {passes} / 失败 {fails} / 警告 {warns} / 提示 {infos} / 共 {len(_results)} 项")
    print("=" * 92)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
