"""端到端冒烟测试：按演示流程逐模块调用真实 API。

用法（服务需先启动）：
    python smoke_test.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010/api"
PASS, FAIL = [], []


def call(method: str, path: str, token: str | None = None, body: dict | None = None,
         expect: int = 200) -> tuple[bool, object]:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            val = json.loads(raw) if raw else None
            ok = r.status == expect
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            val = json.loads(raw)
        except Exception:
            val = raw
        ok = e.code == expect
    except Exception as e:
        val, ok = str(e), False

    tag = f"{method:6} {path}"
    if ok:
        PASS.append(tag)
        print(f"  [OK]   {tag}")
    else:
        FAIL.append((tag, val))
        print(f"  [FAIL] {tag} -> {str(val)[:220]}")
    return ok, val


def main() -> None:
    print("=" * 78)
    print("园智汇 · 端到端冒烟测试")
    print("=" * 78)

    # ---------------------------------------------------------- 0 基础
    print("\n[0] 服务与健康检查")
    call("GET", "/health")
    call("GET", "/meta")
    _, root = call("GET", "/api/", expect=404)

    # ---------------------------------------------------------- 1 登录
    print("\n[1] 认证与权限")
    ok, tok = call("POST", "/auth/login",
                   body={"username": "admin", "password": "Park@2026"})
    if not ok or not isinstance(tok, dict):
        print("\n登录失败，后续用例无法继续。")
        _summary()
        return
    token = tok.get("access_token")
    u = tok.get("user") or {}
    print(f"       账号：{u.get('real_name')} | 角色：{u.get('role_label')} "
          f"| 权限点：{len(u.get('permissions') or [])} | 数据范围：{u.get('data_scope')}")
    call("GET", "/auth/me", token)
    call("GET", "/system/me/permissions", token)
    _, parks = call("GET", "/auth/parks", token)
    park_id = None
    if isinstance(parks, dict):
        lst = parks.get("items") or parks.get("parks") or []
        if lst:
            park_id = lst[0].get("id")
    park_q = f"?park_id={park_id}" if park_id else ""

    # ---------------------------------------------------------- 2 驾驶舱
    print("\n[2] 数据驾驶舱")
    _, dash = call("GET", f"/dashboard/summary{park_q}", token)
    if isinstance(dash, dict):
        kpis = dash.get("kpis") or []
        print(f"       KPI 数量：{len(kpis)}")
        for k in kpis[:6]:
            print(f"        · {k.get('label')}：{k.get('value')}{k.get('unit') or ''}")
    call("GET", f"/dashboard/alerts{park_q}", token)
    call("GET", "/dashboard/quick-stats", token)

    # ---------------------------------------------------------- 3 空间资产
    print("\n[3] 空间资产与数字孪生")
    _, sp = call("GET", f"/space/parks{park_q}", token)
    call("GET", f"/space/buildings{park_q}", token)
    if park_id:
        call("GET", f"/space/parks/{park_id}/twin", token)
    _, bl = call("GET", f"/space/buildings{park_q}", token)
    if isinstance(bl, dict) and (bl.get("items") or bl.get("list")):
        bid = (bl.get("items") or bl.get("list"))[0].get("id")
        call("GET", f"/space/buildings/{bid}", token)
        call("GET", f"/space/spaces/board/{bid}", token)
    _sp = call("GET", f"/space/spaces{park_q}&page_size=5" if park_q else "/space/spaces?page_size=5", token)

    # ---------------------------------------------------------- 4 企业服务
    print("\n[4] 企业与政策服务")
    _, ents = call("GET", f"/enterprise/enterprises{park_q}&page_size=5" if park_q
                   else "/enterprise/enterprises?page_size=5", token)
    if isinstance(ents, dict) and ents.get("items"):
        eid = ents["items"][0]["id"]
        _, ed = call("GET", f"/enterprise/enterprises/{eid}", token)
        if isinstance(ed, dict):
            ent = ed.get("enterprise") if isinstance(ed.get("enterprise"), dict) else ed
            print(f"       企业：{ent.get('enterprise_name')} | 风险信号："
                  f"{len(ed.get('risk_signals') or ed.get('risks') or [])} 条")
    call("GET", "/enterprise/policies", token)
    call("GET", "/enterprise/policy-matches?page_size=5", token)
    call("GET", "/enterprise/service-requests?page_size=5", token)
    call("GET", "/enterprise/enterprises/meta/industries", token)

    # ---------------------------------------------------------- 5 招商
    print("\n[5] 招商运营")
    call("GET", "/leasing/channels", token)
    _, fn = call("GET", f"/leasing/funnel{park_q}", token)
    if isinstance(fn, dict):
        print(f"       漏斗阶段：{len(fn.get('stages') or fn.get('funnel') or [])}")
    call("GET", "/leasing/leads?page_size=5", token)
    call("GET", "/leasing/activities?page_size=5", token)
    call("GET", "/leasing/stagnant", token)

    # ---------------------------------------------------------- 6 合同财务
    print("\n[6] 合同与财务")
    call("GET", "/contracts?page_size=5", token)
    call("GET", "/contracts/expiring", token)
    _, bs = call("GET", f"/finance/bills{park_q}&page_size=5" if park_q
                 else "/finance/bills?page_size=5", token)
    _, fs = call("GET", f"/finance/summary{park_q}", token)
    if isinstance(fs, dict):
        # 财务汇总的指标集中在 kpi 下
        s = fs.get("kpi") if isinstance(fs.get("kpi"), dict) else fs
        print(f"       应收：{s.get('total_receivable')} | 实收：{s.get('total_received')} "
              f"| 收缴率：{s.get('collection_rate')}% | 逾期：{s.get('total_arrears')}")
    call("GET", "/finance/payments?page_size=5", token)
    call("GET", "/finance/projects/investment", token)

    # ---------------------------------------------------------- 7 项目管理
    print("\n[7] 项目管理（CPM + EVM + 敏捷）")
    _, pf = call("GET", f"/projects/portfolio{park_q}", token)
    _, pl = call("GET", f"/projects?page_size=50{park_q.replace('?','&') if park_q else ''}".replace("&&","&"), token)
    items = (pl or {}).get("items") if isinstance(pl, dict) else None
    if not items and isinstance(pl, dict):
        items = pl.get("list")
    proj_id = items[0]["id"] if items else None
    if proj_id:
        _, pd = call("GET", f"/projects/{proj_id}", token)
        if isinstance(pd, dict):
            # 项目主体嵌在 project 字段下，关键路径嵌在 critical_path 下
            pj = pd.get("project") if isinstance(pd.get("project"), dict) else pd
            print(f"       项目：{pj.get('project_name')} | 方式：{pj.get('management_method')} "
                  f"| 进度：{pj.get('progress')}% / 计划 {pj.get('planned_progress')}% "
                  f"| 健康度：{pj.get('health')}")
            cp = pd.get("critical_path") or {}
            if isinstance(cp, dict) and cp:
                tasks = cp.get("tasks") or cp.get("items") or []
                span = [t for t in tasks if t.get("early_finish_day") is not None]
                total_days = (max(t["early_finish_day"] for t in span) if span else None)
                print(f"       关键路径任务：{len(tasks)} 个 | 项目工期：{total_days} 天")
        call("GET", f"/projects/{proj_id}/gantt", token)
        _, evm = call("GET", f"/projects/{proj_id}/evm", token)
        if isinstance(evm, dict):
            e = evm.get("evm") if isinstance(evm.get("evm"), dict) else evm
            print(f"       EVM CPI={e.get('cpi')} SPI={e.get('spi')} "
                  f"EAC={e.get('eac')} VAC={e.get('vac')}")
        call("GET", f"/projects/{proj_id}/risks", token)
        call("GET", f"/projects/{proj_id}/milestones", token)
        # 敏捷视图仅对 AGILE/HYBRID 项目开放；瀑布式项目返回 400 是预期行为
        _check_agile(proj_id, token)
    call("GET", "/finance/projects/investment", token)

    # ---------------------------------------------------------- 8 物业运维
    print("\n[8] 物业运维、能源与安全")
    call("GET", f"/operation/work-orders{park_q}&page_size=5" if park_q
         else "/operation/work-orders?page_size=5", token)
    call("GET", "/operation/work-orders/stats/by-type", token)
    call("GET", "/operation/devices?page_size=5", token)
    _, en = call("GET", f"/operation/energy/summary{park_q}", token)
    if isinstance(en, dict):
        print(f"       能源：总量 {en.get('total_value')} | 同比 {en.get('yoy')}%")
    call("GET", f"/operation/safety/summary{park_q}", token)
    call("GET", "/operation/safety/incidents?page_size=5", token)
    call("GET", "/operation/safety/hazards?page_size=5", token)
    call("GET", "/operation/parking/overview", token)

    # ---------------------------------------------------------- 9 审批中心
    print("\n[9] 审批中心")
    call("GET", "/approvals?page_size=5", token)
    _, todo = call("GET", "/approvals/todo", token)
    if isinstance(todo, dict):
        print(f"       我的待办审批：{todo.get('total', len(todo.get('items') or []))} 条")

    # ---------------------------------------------------------- 10 AI Agent
    print("\n[10] AI Agent（主 Agent + 子 Agent）")
    _, ags = call("GET", "/agent/agents", token)
    if isinstance(ags, dict):
        print(f"       主 Agent：{(ags.get('main') or {}).get('name')} "
              f"| 子 Agent：{len(ags.get('sub_agents') or [])} 个")
    call("GET", "/agent/tools", token)
    questions = [
        "当前园区整体经营情况怎么样？",
        "哪些企业存在经营风险？",
        "招商渠道哪个效果最好？",
    ]
    for q in questions:
        ok, r = call("POST", "/agent/chat", token,
                     body={"question": q, "park_id": park_id})
        if ok and isinstance(r, dict):
            resp = r.get("response") or {}
            keys = [k for k in resp if isinstance(resp, dict)] if isinstance(resp, dict) else []
            print(f"       Q: {q}")
            print(f"         意图={r.get('intent_label')} | 权限={r.get('permission_level')} "
                  f"| 数据充足={r.get('data_sufficient')} | 耗时={r.get('latency_ms')}ms "
                  f"| 输出分区={len(keys)}")
    _, recs = call("GET", "/agent/recommendations?page_size=5", token)
    if isinstance(recs, dict):
        st = recs.get("stats") or {}
        print(f"       AI 建议：{st.get('total')} 条 | 待处理 {st.get('pending')} "
              f"| 需审批 {st.get('needs_approval')}")
    call("GET", "/agent/daily-insight", token)
    call("GET", "/agent/conversations", token)
    if proj_id:
        call("GET", f"/agent/pm/{proj_id}", token)

    # ---------------------------------------------------------- 11 数据中心
    print("\n[11] 数据中心")
    _, cat = call("GET", "/data/catalog", token)
    if isinstance(cat, dict):
        s = cat.get("summary") or {}
        print(f"       数据资产：{s.get('table_total')} 张表 / {s.get('row_total')} 行 "
              f"/ {s.get('domain_total')} 个主题域")
    call("GET", "/data/quality", token)
    call("GET", "/data/uploads?page_size=5", token)
    _, lg = call("GET", "/data/lineage", token)
    if isinstance(lg, dict):
        print(f"       血缘链路：{len(lg.get('chains') or [])} 个核心指标")

    # ---------------------------------------------------------- 12 报表中心
    print("\n[12] 报表中心")
    call("GET", "/report/types", token)
    _, rm = call("GET", f"/report/park-monthly{park_q}", token)
    if isinstance(rm, dict):
        print(f"       月报：{rm.get('report_name')} | 章节 {len(rm.get('sections') or [])} 段 "
              f"| 预警 {len((rm.get('executive_summary') or {}).get('warnings') or [])} 条")
    if proj_id:
        _, pr = call("GET", f"/report/project/{proj_id}?report_type=WEEKLY", token)
        if isinstance(pr, dict):
            print(f"       项目周报：{pr.get('report_name')} | 章节 {len(pr.get('sections') or [])} 段")
    call("GET", "/report/archive?page_size=5", token)
    _, gen = call("POST", f"/report/generate?report_type=PARK_MONTHLY&fmt=MARKDOWN"
                          + (f"&park_id={park_id}" if park_id else ""), token)
    if isinstance(gen, dict):
        print(f"       生成归档：{gen.get('report_code')} | Markdown "
              f"{len(gen.get('markdown') or '')} 字符")
        _export_markdown(gen.get("id"), token)

    # ---------------------------------------------------------- 13 通知
    print("\n[13] 消息通知")
    _, nc = call("GET", "/notification/unread-count", token)
    if isinstance(nc, dict):
        print(f"       未读 {nc.get('unread')} | 紧急未读 {nc.get('critical_unread')} "
              f"| 未处理 {nc.get('unhandled')}")
    call("GET", "/notification?page_size=5", token)
    call("GET", "/notification/stats", token)
    call("GET", "/notification/timeline/recent", token)

    # ---------------------------------------------------------- 14 审计
    print("\n[14] 日志审计")
    _, au = call("GET", "/audit?page_size=5", token)
    if isinstance(au, dict):
        st = au.get("stats") or {}
        print(f"       审计日志：{st.get('total')} 条 | AI 调用 {st.get('ai_calls')} "
              f"| 高风险操作 {st.get('risk_operations')}")
    call("GET", "/audit/stats", token)
    call("GET", "/audit/meta/dict", token)

    # ---------------------------------------------------------- 15 系统管理
    print("\n[15] 系统管理")
    call("GET", "/system/dict", token)
    call("GET", "/system/organizations", token)
    call("GET", "/system/parks", token)
    _, tpl = call("GET", "/system/templates", token)
    if isinstance(tpl, dict):
        print(f"       园区模板：{tpl.get('total')} 个")
    call("GET", "/system/users?page_size=5", token)
    _, rl = call("GET", "/system/roles", token)
    if isinstance(rl, dict):
        s = rl.get("summary") or {}
        print(f"       角色 {s.get('role_total')} 个 | 权限点 {s.get('permission_total')} "
              f"| 角色权限绑定 {s.get('binding_total')}")
    call("GET", "/system/permissions", token)

    # ---------------------------------------------------------- 16 权限隔离
    print("\n[16] 权限隔离验证（越权访问应被拒绝）")
    for uname, pwd in [("p1_manager", "Park@2026"), ("tenant1", "Park@2026")]:
        ok, t = call("POST", "/auth/login", body={"username": uname, "password": pwd})
        if ok and isinstance(t, dict):
            tk = t["access_token"]
            usr = t.get("user") or {}
            print(f"       {uname}｜角色={usr.get('role_label')}｜范围={usr.get('data_scope')}"
                  f"｜可见园区={usr.get('visible_park_ids')}")
            call("GET", "/dashboard/summary", tk)
            # 用「该角色确实没有该权限」的模块做越权断言，避免误判：
            # 系统管理（角色配置）仅集团级管理员可读，园区/企业角色必然 403
            call("GET", "/system/roles", tk, expect=403)
        else:
            print(f"       {uname} 登录失败（可能账号名不同）")

    _summary()


def _summary() -> None:
    print("\n" + "=" * 78)
    print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("\n失败明细：")
        for tag, val in FAIL:
            print(f"  · {tag}")
            print(f"    {str(val)[:400]}")
    print("=" * 78)
    sys.exit(0 if not FAIL else 1)


def _export_markdown(rec_id, token: str) -> None:
    """Markdown 导出返回 text/markdown，需按文本读取。"""
    url = BASE + f"/report/archive/{rec_id}/export"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    tag = f"GET    /report/archive/{rec_id}/export"
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            disp = r.headers.get("Content-Disposition") or ""
            ok = r.status == 200 and len(body) > 200 and "filename*" in disp
    except urllib.error.HTTPError as e:
        body, ok = e.read().decode("utf-8", "ignore"), False
    if ok:
        PASS.append(tag)
        print(f"  [OK]   {tag}  （Markdown {len(body)} 字符，含 UTF-8 文件名）")
    else:
        FAIL.append((tag, body[:200]))
        print(f"  [FAIL] {tag} -> {body[:200]}")


def _check_agile(project_id: int, token: str) -> None:
    """敏捷视图：AGILE/HYBRID 项目必须返回看板；瀑布式返回 400 属预期。"""
    tag = f"GET    /projects/{project_id}/agile"
    url = BASE + f"/projects/{project_id}/agile"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            val = json.loads(r.read().decode())
            sprints = val.get("sprints") or []
            if sprints:
                sid = sprints[0]["id"]
                call("GET", f"/sprints/{sid}/board", token)
            PASS.append(tag)
            print(f"  [OK]   {tag}  （{len(sprints)} 个 Sprint）")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        if e.code == 400:
            PASS.append(tag)
            print(f"  [OK]   {tag}  （瀑布式项目，按业务规则不适用敏捷视图 —— 预期）")
        else:
            FAIL.append((tag, body[:200]))
            print(f"  [FAIL] {tag} -> {body[:200]}")


if __name__ == "__main__":
    main()
