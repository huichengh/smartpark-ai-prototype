#!/usr/bin/env python
"""经营决策计算的金标准用例（确定性、可复现、不需要启动服务）。

为什么必须有这套：经营沙盘的价值全在"同一个输入必得同一个数"。
一旦有人改了公式或口径，这几条断言会立刻炸——比页面看起来正常可靠得多。

覆盖提示词 11 点名的边界：0 值、负值、免租、折扣、反常输入、空置期跨月。

用法：python check_operating.py        退出码 0=全过，1=有失败
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.services import operating_engine as E  # noqa: E402

_results: list[tuple[bool, str, str]] = []


def check(cond: bool, name: str, detail: str = "") -> None:
    _results.append((bool(cond), name, detail))


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def base(**kw) -> E.LeaseScenario:
    """标准样例：1200㎡、45 元/㎡/月、36 个月、空置 90 天、持有成本 8000/月。"""
    p = dict(area=1200, list_rent=45, lease_months=36, vacancy_days=90,
             service_cost_monthly=8000)
    p.update(kw)
    return E.LeaseScenario(**p)


# --------------------------------------------------------------------- 基础口径
r = E.evaluate(base())
check(near(r.monthly_rent, 54000), "月租金 = 面积 × 单价", f"{r.monthly_rent}")
check(near(r.gross_rent_total, 54000 * 36), "无免租时租期租金 = 月租金 × 租期",
      f"{r.gross_rent_total}")
check(near(r.commission, 27000), "佣金 = 月租金 × 0.5", f"{r.commission}")
check(near(r.service_cost_total, 8000 * 36), "持有成本 = 月成本 × 租期",
      f"{r.service_cost_total}")
check(near(r.net_contribution, 1944000 - 27000 - 288000), "净贡献扣除佣金与持有成本",
      f"{r.net_contribution}")

# --------------------------------------------------------------------- 免租期
r = E.evaluate(base(rent_free_months=3))
check(near(r.gross_rent_total, 54000 * 33), "免租 3 个月 → 只计 33 个月租金",
      f"{r.gross_rent_total}")
check(near(r.rent_free_value, 54000 * 3), "免租让价金额如实单列", f"{r.rent_free_value}")
# 免租月内不应产生租金入账
lease_months = [c for c in r.cash_flow if c["phase"] == "LEASE"]
check(all(c["inflow"] == 0 for c in lease_months[:3]), "免租期内现金流入账为 0")
check(lease_months[3]["inflow"] > 0, "免租期结束后开始计租")

# --------------------------------------------------------------------- 折扣
r = E.evaluate(base(discount=0.10))
check(near(r.effective_rent, 40.5), "让价 10% → 实收单价 40.5", f"{r.effective_rent}")
check(near(r.monthly_rent, 48600), "让价后月租金按实收单价计算", f"{r.monthly_rent}")

# --------------------------------------------------------------------- 空置期进入现金流
r = E.evaluate(base(vacancy_days=90))
check(len(r.cash_flow) == 3 + 36, "现金流总月数 = 空置月数 + 租期", f"{len(r.cash_flow)}")
check(all(c["inflow"] == 0 for c in r.cash_flow[:3]), "空置期内无租金入账")
check(all(c["outflow"] > 0 for c in r.cash_flow[:3]), "空置期仍发生持有成本")
check(r.first_cash_month == 4, "空置 90 天 → 首次回款在第 4 月", f"{r.first_cash_month}")

# 空置期向上取整：45 天应按 2 个月计
r45 = E.evaluate(base(vacancy_days=45))
check(len([c for c in r45.cash_flow if c["phase"] == "VACANCY"]) == 2,
      "空置 45 天按 2 个月向上取整")

# 空置越久，回本越晚（单调性）
a = E.evaluate(base(vacancy_days=30))
b = E.evaluate(base(vacancy_days=180))
check((a.payback_month or 999) <= (b.payback_month or 999),
      "空置期越长，现金流回正不早于短空置方案",
      f"{a.payback_month} vs {b.payback_month}")

# --------------------------------------------------------------------- 非法输入必须拒算
def should_raise(**kw) -> bool:
    try:
        E.evaluate(base(**kw))
    except E.ScenarioInputError:
        return True
    except Exception:
        return False
    return False


check(should_raise(area=0), "面积为 0 → 拒绝推演")
check(should_raise(area=-100), "负面积 → 拒绝推演")
check(should_raise(list_rent=0), "挂牌租金为 0 → 拒绝推演")
check(should_raise(discount=0.6), "让价 60% 超上限 → 拒绝推演")
check(should_raise(rent_free_months=36), "免租期 ≥ 租期 → 拒绝推演")
check(should_raise(vacancy_days=-1), "负空置天数 → 拒绝推演")
check(should_raise(lease_months=0), "租期为 0 → 拒绝推演")
check(should_raise(vacancy_days=400), "空置超 365 天 → 拒绝推演（提示先核实数据）")

# --------------------------------------------------------------------- 三方案对比
cmp = E.compare(base())
check(len(cmp["scenarios"]) == 3, "三方案对比返回 A/B/C 三套")
check(cmp["requires_human_decision"] is True, "对比结果明确要求人工决策")
check(cmp["scenarios"][0]["delta_vs_a"] == 0, "方案 A 相对自身差额为 0")
base_net = cmp["scenarios"][0]["net_contribution"]
for s in cmp["scenarios"][1:]:
    check(near(s["delta_vs_a"], round(s["net_contribution"] - base_net, 2)),
          f"{s['label']} 的差额 = 净贡献 − 方案A 净贡献")
check(cmp["assumptions"]["version"] == E.ASSUMPTION_VERSION, "结果带口径版本号")
check("演示假设" in cmp["assumptions"]["statement"], "结果带「演示假设」声明")

# --------------------------------------------------------------------- 敏感性
sens = E.sensitivity(base())
check(len(sens["rows"]) >= 2, "敏感性至少给出两个扰动情景")
# 让价越高净贡献越低（同空置期下）
rows = {r["name"]: r for r in sens["rows"]}
if "让价 5%" in rows and "让价 15%" in rows:
    check(rows["让价 15%"]["net_contribution"] < rows["让价 5%"]["net_contribution"],
          "让价越高净贡献越低")

# --------------------------------------------------------------------- 汇总
fails = [x for x in _results if not x[0]]
print("=" * 88)
print("经营决策金标准用例")
print("=" * 88)
for ok, name, detail in _results:
    print(("  ✔ " if ok else "  ✘ ") + name + (f"  ← {detail}" if detail and not ok else ""))
print("=" * 88)
print(f"结果：通过 {len(_results) - len(fails)} / 失败 {len(fails)} / 共 {len(_results)}")
print("=" * 88)
raise SystemExit(1 if fails else 0)
