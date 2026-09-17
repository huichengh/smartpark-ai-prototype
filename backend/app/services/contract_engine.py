"""合同口径的唯一实现处。

为什么需要这个模块：**「90 天内到期合同」这个指标一度有四份实现**，其中两份漏了
状态判断，把已终止（TERMINATED）的合同也算成"即将到期"：

| 位置 | 状态过滤 | 结果 |
|---|---|---|
| `dashboard_service` 驾驶舱 KPI | ✔ 只算生效中/即将到期 | 37 |
| `api/v1/contract.py` 的 `stats.expiring_90` | ✘ 只看日期 | **39** |
| `dashboard_service` 的 `contract_expiring` 字段 | ✘ 只看日期 | **39** |
| `api/v1/enterprise.py` 一企一档 | ✔ | 37 |

差额是 2 份已终止合同——它们不可能续租，算进「到期预警」会凭空多出催办任务，
也让驾驶舱与合同页显示两个数、被问到就只能解释。

同一指标多份实现的代价不是"重复代码"，而是**两个数都看起来对**。所以这里集中定义，
任何地方要用"到期预警"语义都必须调用 `is_expiring_within`。
"""
from __future__ import annotations

import datetime as dt

#: 允许进入「到期预警」的合同状态。
#: 已到期（EXPIRED）与已终止（TERMINATED）不在此列——前者属于逾期处置，后者已失效。
EXPIRING_WINDOW_STATUSES: tuple[str, ...] = ("ACTIVE", "EXPIRING")


def days_left_of(end_date: dt.date | None, today: dt.date) -> int | None:
    """到期日距今天数；无到期日返回 None。"""
    if end_date is None:
        return None
    return (end_date - today).days


def is_expiring_within(status: str | None, days_left: int | None, window: int) -> bool:
    """合同是否处于「window 天内到期」状态。

    window 为天数窗口（如 30 / 90）；days_left 必须是 `days_left_of` 的返回值。
    口径：状态属于 EXPIRING_WINDOW_STATUSES，且 0 <= days_left <= window。
    """
    if status not in EXPIRING_WINDOW_STATUSES or days_left is None:
        return False
    return 0 <= days_left <= window


def is_expiring_on(status: str | None, end_date: dt.date | None,
                   today: dt.date, window: int) -> bool:
    """便捷版：直接传 end_date，内部换算 days_left。"""
    return is_expiring_within(status, days_left_of(end_date, today), window)
