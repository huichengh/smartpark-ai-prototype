"""经营决策计算引擎 —— 招商方案收益推演（确定性纯函数）。

为什么单独成文件、且全部是纯函数：

1. **财务数字不能由模型"心算"**。提示词 04 / 建议书 3.3 都明确要求：
   沙盘结果必须可由同一组输入重新算出同一个数，LLM 只能解释、不能生成数字。
   所以这里没有任何 I/O、没有数据库、没有随机数——给定输入必得同一输出，
   可以直接做金标准回归（见 check_operating.py）。
2. **口径只能有一份**。项目历史上"90 天内到期"这个指标被写了四遍、出现 37/39
   两个值（见 docs/测试日记.md 缺陷 2），所以出租率、净贡献这些必须集中定义。
3. **假设必须显式**。所有默认值都标注为"演示假设"，随结果一起返回，
   避免把推演值当成真实预测。

单位约定（全项目统一，别改）：
    area ㎡ ｜ rent 元/㎡/月 ｜ 金额 元 ｜ 时长 月
月租金 = area × rent；空置损失按 30 天/月 折算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# —— 口径与边界（改这里就等于改全系统口径，所以集中在此）————————————————
DAYS_PER_MONTH = 30
MAX_DISCOUNT = 0.50          # 让价上限：超过 50% 必须人工特批，系统直接拒算
MAX_RENT_FREE_MONTHS = 12
MAX_LEASE_MONTHS = 240       # 20 年
ASSUMPTION_VERSION = "v1.0"


class ScenarioInputError(ValueError):
    """输入不合法。**禁止静默兜底**——宁可拒算并说明原因，也不返回一个看起来合理的错数。"""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"{field}：{message}")


@dataclass
class LeaseScenario:
    """一份招商方案的输入参数。"""

    area: float                       # 可出租面积（㎡）
    list_rent: float                  # 挂牌租金（元/㎡/月）
    lease_months: int                 # 租期（月）
    discount: float = 0.0             # 让价比例，0.10 = 让价 10%
    rent_free_months: int = 0         # 免租期（月）
    vacancy_days: int = 0             # 预计空置天数（从今天到起租）
    commission_months: float = 0.5    # 招商佣金 = 月租金 × 倍数
    fitout_per_sqm: float = 0.0       # 装修补贴（元/㎡）
    service_cost_monthly: float = 0.0  # 月度持有/服务成本（元/月）
    payment_cycle_days: int = 30      # 回款周期（天）
    label: str = ""
    key: str = ""
    user_discount: float | None = None   # 使用者显式指定的让价（覆盖 B 的预设）

    def validate(self) -> None:
        if self.area is None or self.area <= 0:
            raise ScenarioInputError("area", "面积必须大于 0；没有可信面积时不允许推演")
        if self.list_rent is None or self.list_rent <= 0:
            raise ScenarioInputError("list_rent", "挂牌租金必须大于 0")
        if not (0 <= self.discount <= MAX_DISCOUNT):
            raise ScenarioInputError(
                "discount", f"让价比例必须在 0–{MAX_DISCOUNT:.0%} 之间（更高让价需人工特批，系统不代算）")
        if self.lease_months is None or not (1 <= self.lease_months <= MAX_LEASE_MONTHS):
            raise ScenarioInputError("lease_months", f"租期必须在 1–{MAX_LEASE_MONTHS} 个月之间")
        if not (0 <= self.rent_free_months <= MAX_RENT_FREE_MONTHS):
            raise ScenarioInputError("rent_free_months", f"免租期必须在 0–{MAX_RENT_FREE_MONTHS} 个月之间")
        if self.rent_free_months >= self.lease_months:
            raise ScenarioInputError("rent_free_months", "免租期不能大于等于租期（否则没有计租月份）")
        if self.vacancy_days < 0:
            raise ScenarioInputError("vacancy_days", "空置天数不能为负")
        if self.vacancy_days > 365:
            raise ScenarioInputError("vacancy_days", "空置天数超过 365 天，请先核实数据再推演")
        if self.fitout_per_sqm < 0:
            raise ScenarioInputError("fitout_per_sqm", "装修补贴不能为负")
        if self.service_cost_monthly < 0:
            raise ScenarioInputError("service_cost_monthly", "服务成本不能为负")
        if self.commission_months < 0 or self.commission_months > 6:
            raise ScenarioInputError("commission_months", "佣金倍数应在 0–6 个月之间")
        if not (0 <= self.payment_cycle_days <= 180):
            raise ScenarioInputError("payment_cycle_days", "回款周期应在 0–180 天之间")


@dataclass
class ScenarioResult:
    """一份方案的测算结果 + 全部假设。"""

    key: str
    label: str
    effective_rent: float
    monthly_rent: float
    gross_rent_total: float
    rent_free_value: float
    commission: float
    fitout_cost: float
    service_cost_total: float
    vacancy_loss: float
    net_contribution: float
    net_after_vacancy: float
    payback_month: int | None
    first_cash_month: int | None = None
    cash_flow: list[dict[str, Any]] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "effective_rent": round(self.effective_rent, 2),
            "monthly_rent": round(self.monthly_rent, 2),
            "gross_rent_total": round(self.gross_rent_total, 2),
            "rent_free_value": round(self.rent_free_value, 2),
            "commission": round(self.commission, 2),
            "fitout_cost": round(self.fitout_cost, 2),
            "service_cost_total": round(self.service_cost_total, 2),
            "vacancy_loss": round(self.vacancy_loss, 2),
            "net_contribution": round(self.net_contribution, 2),
            "net_after_vacancy": round(self.net_after_vacancy, 2),
            "payback_month": self.payback_month,
            "first_cash_month": self.first_cash_month,
            "cash_flow": self.cash_flow,
            "assumptions": self.assumptions,
        }


def _assumptions(s: LeaseScenario) -> dict[str, Any]:
    return {
        "version": ASSUMPTION_VERSION,
        "days_per_month": DAYS_PER_MONTH,
        "rent_unit": "元/㎡/月",
        "area_unit": "㎡",
        "currency": "CNY",
        "statement": "演示假设：租金、空置期、佣金与装修补贴均为输入参数，非市场真实报价；"
                     "结果用于方案比较，不构成收益承诺。",
        "vacancy_loss_basis": "按挂牌价 × 面积 × 空置天数/30 计算的机会成本，单独列示、不从净贡献中重复扣减",
        "net_contribution_basis": "租期内实收租金 − 招商佣金 − 装修补贴 − 持有/服务成本（不含空置期机会成本）",
        "cash_flow_basis": "现金流从今天起算：先空置期（只有持有成本、无租金），再进入租期；"
                           "空置期按 30 天/月向上取整",
        "payback_note": "payback_month 指从今天起净现金流累计转正的第几个月；"
                        "first_cash_month 指首次产生租金收入的月份",
        "payment_cycle_note": f"回款周期 {s.payment_cycle_days} 天仅影响现金流月份分布，不改变总额",
    }


def evaluate(s: LeaseScenario) -> ScenarioResult:
    """测算单个方案。输入不合法时抛 ScenarioInputError，绝不返回兜底数字。"""
    s.validate()

    effective_rent = s.list_rent * (1 - s.discount)
    monthly_rent = s.area * effective_rent
    paid_months = s.lease_months - s.rent_free_months
    gross_rent_total = monthly_rent * paid_months
    rent_free_value = monthly_rent * s.rent_free_months
    commission = monthly_rent * s.commission_months
    fitout_cost = s.area * s.fitout_per_sqm
    service_cost_total = s.service_cost_monthly * s.lease_months
    vacancy_loss = s.area * s.list_rent * s.vacancy_days / DAYS_PER_MONTH

    net_contribution = gross_rent_total - commission - fitout_cost - service_cost_total

    # 逐月现金流：**从今天起算**，先经历空置期，再进入租期。
    #
    # 为什么必须含空置期：若只画租期内的现金流，空置 90 天的方案会显示"回本更快"，
    # 与直觉相反——因为等待期不产生租金却照样发生持有成本。决策者比较的正是
    # "现在就做"的方案，所以时间轴必须从今天开始。
    vacancy_months = -(-s.vacancy_days // DAYS_PER_MONTH)   # 向上取整
    total_months = vacancy_months + s.lease_months
    cash_flow: list[dict[str, Any]] = []
    cumulative = 0.0
    payback_month: int | None = None
    first_cash_month: int | None = None
    for m in range(1, total_months + 1):
        in_vacancy = m <= vacancy_months
        lease_month = m - vacancy_months            # 1-based 租期内的第几个月
        if in_vacancy:
            inflow = 0.0
            outflow = s.service_cost_monthly        # 空置期仍要付持有/服务成本
        else:
            inflow = 0.0 if lease_month <= s.rent_free_months else monthly_rent
            outflow = s.service_cost_monthly
            if lease_month == 1:
                outflow += commission + fitout_cost  # 签约当月一次性发生
            if inflow > 0 and first_cash_month is None:
                first_cash_month = m
        net = inflow - outflow
        cumulative += net
        if payback_month is None and cumulative >= 0:
            payback_month = m
        cash_flow.append({
            "month": m,
            "phase": "VACANCY" if in_vacancy else "LEASE",
            "inflow": round(inflow, 2),
            "outflow": round(outflow, 2),
            "net": round(net, 2),
            "cumulative": round(cumulative, 2),
            "rent_free": (not in_vacancy) and lease_month <= s.rent_free_months,
        })

    return ScenarioResult(
        key=s.key, label=s.label,
        effective_rent=effective_rent, monthly_rent=monthly_rent,
        gross_rent_total=gross_rent_total, rent_free_value=rent_free_value,
        commission=commission, fitout_cost=fitout_cost,
        service_cost_total=service_cost_total, vacancy_loss=vacancy_loss,
        net_contribution=net_contribution,
        # 决策口径：把空置期的机会成本也扣掉。租期净贡献不含空置，
        # 否则"等一年"与"等三个月"会算出同一个数，回答就跟问题无关了。
        net_after_vacancy=net_contribution - vacancy_loss,
        payback_month=payback_month,
        first_cash_month=first_cash_month,
        cash_flow=cash_flow, assumptions=_assumptions(s),
    )


def sensitivity(base: LeaseScenario) -> dict[str, Any]:
    """敏感性分析：让价 ±5pp、空置期 ±30 天对净贡献的影响。

    只做单变量扰动（其余参数不动），避免多变量联动让人读不出因果。
    """
    base_result = evaluate(base)
    rows: list[dict[str, Any]] = []

    def _row(name: str, scenario: LeaseScenario) -> None:
        r = evaluate(scenario)
        rows.append({
            "name": name,
            "net_contribution": round(r.net_contribution, 2),
            "delta": round(r.net_contribution - base_result.net_contribution, 2),
            "payback_month": r.payback_month,
        })

    for delta in (-0.05, 0.05):
        d = round(base.discount + delta, 4)
        if 0 <= d <= MAX_DISCOUNT:
            s2 = LeaseScenario(**{**base.__dict__, "discount": d, "key": f"d{d}", "label": f"让价 {d:.0%}"})
            _row(f"让价 {d:.0%}", s2)

    for delta in (-30, 30):
        v = base.vacancy_days + delta
        if 0 <= v <= 365:
            s3 = LeaseScenario(**{**base.__dict__, "vacancy_days": v, "key": f"v{v}", "label": f"空置 {v} 天"})
            _row(f"空置 {v} 天", s3)

    return {
        "base_net_contribution": round(base_result.net_contribution, 2),
        "rows": rows,
        "note": "单变量扰动，其余参数保持不变；仅用于观察方向与量级，不是预测区间。",
    }


# ---------------------------------------------------------------------------
# 三方案预设：A 维持原价 / B 降价快速出租 / C 分割改造后出租
# ---------------------------------------------------------------------------
# 预设只调整**可解释的参数**，不做任何"降价一定更快出租"的假定——
# 空置天数由使用者填写，系统不替它猜。
SCENARIO_PRESETS: dict[str, dict[str, Any]] = {
    "A": {"label": "A 维持挂牌价续谈", "discount": 0.0, "vacancy_days_delta": 0,
          "rent_free_months": 0, "fitout_per_sqm": 0.0, "note": "价格不动，按当前空置预期等待签约"},
    "B": {"label": "B 让价快速成交", "discount": 0.10, "vacancy_days_delta": -45,
          "rent_free_months": 1, "fitout_per_sqm": 0.0, "note": "让价 10%、加 1 个月免租，换取提前起租"},
    "C": {"label": "C 分割改造后出租", "discount": 0.05, "vacancy_days_delta": 30,
          "rent_free_months": 2, "fitout_per_sqm": 300.0,
          "note": "增加改造投入、空置更久，换取更高单位租金（需改造可行性确认）"},
}


def build_presets(base: LeaseScenario) -> list[LeaseScenario]:
    """以当前空间参数为底，生成 A/B/C 三套可比较方案。"""
    out: list[LeaseScenario] = []
    for key, p in SCENARIO_PRESETS.items():
        raw = base.vacancy_days + int(p["vacancy_days_delta"])
        # 基准空置期本身可能接近上限（例如用户问"空置要等一年"），加上方案偏移后会越界。
        # 这里**封顶并标注**，而不是让它把整个推演打回"数据不足"——用户问的是正常的假设情景。
        vacancy = max(0, min(365, raw))
        out.append(LeaseScenario(
            area=base.area,
            list_rent=base.list_rent * (1.15 if key == "C" else 1.0),  # 分割改造后单位租金按 +15% 假设
            lease_months=base.lease_months,
            # 使用者显式指定让价时，用他的值替换预设（B 是让价方案）；否则沿用预设。
            discount=(base.user_discount if (key == "B" and base.user_discount is not None)
                      else float(p["discount"])),
            rent_free_months=int(p["rent_free_months"]),
            vacancy_days=vacancy,
            commission_months=base.commission_months,
            fitout_per_sqm=float(p["fitout_per_sqm"]),
            service_cost_monthly=base.service_cost_monthly,
            payment_cycle_days=base.payment_cycle_days,
            key=key, label=str(p["label"]),
        ))
    return out


def compare(base: LeaseScenario) -> dict[str, Any]:
    """三方案比较：结果 + 与方案 A 的差额 + 规则化解读（不是"推荐 A"式的伪智能）。"""
    scenarios = build_presets(base)
    results = [evaluate(s) for s in scenarios]
    base_net = results[0].net_contribution

    rows = []
    for s, r in zip(scenarios, results):
        raw_vacancy = base.vacancy_days + int(SCENARIO_PRESETS[s.key]["vacancy_days_delta"])
        note = SCENARIO_PRESETS[s.key]["note"]
        if raw_vacancy > 365:
            note += f"；空置期 {raw_vacancy} 天超出可推演上限，已按 365 天封顶"
        rows.append({
            **r.to_dict(),
            "preset_note": note,
            "delta_vs_a": round(r.net_contribution - base_net, 2),
            "vacancy_days": s.vacancy_days,
            "vacancy_months": -(-s.vacancy_days // DAYS_PER_MONTH),
            "rent_free_months": s.rent_free_months,
            "discount": s.discount,
            "fitout_per_sqm": s.fitout_per_sqm,
        })

    for r in rows:
        r["delta_decision_vs_a"] = round(r["net_after_vacancy"] - rows[0]["net_after_vacancy"], 2)
    best = max(rows, key=lambda x: x["net_after_vacancy"])
    fastest = min(rows, key=lambda x: (x["vacancy_days"], -x["net_after_vacancy"]))

    # 解读只陈述可验证的差异，不下"应当选哪个"的结论——决策由人做（L3）。
    notes = [
        f"扣空置机会成本后净贡献最高：{best['label']}（{best['net_after_vacancy']:,.0f} 元）",
        f"起租最快：{fastest['label']}（预计空置 {fastest['vacancy_days']} 天）",
        "方案 C 的单位租金上调与改造投入均为参数假设，需工程可行性确认后才可执行。",
    ]
    return {
        "base_input": {
            "area": base.area, "list_rent": base.list_rent,
            "lease_months": base.lease_months, "vacancy_days": base.vacancy_days,
            "service_cost_monthly": base.service_cost_monthly,
        },
        "scenarios": rows,
        "sensitivity": sensitivity(base),
        "notes": notes,
        "assumptions": _assumptions(base),
        "requires_human_decision": True,
        "data_label": "演示数据·推演结果",
    }
