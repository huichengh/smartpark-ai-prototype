#!/usr/bin/env python
"""变更影响分析的金标准用例（纯函数，不需要启动服务）。

关键点：这是**工期推演**，不是"延期概率预测"。所以断言都围绕可复算的天数、
关键路径变化与拒算行为，不涉及任何概率。

用法：python check_change_impact.py      退出码 0 = 全过
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.services import change_impact_engine as cie  # noqa: E402
from app.services.project_engine import compute_cpm  # noqa: E402

_results: list[tuple[bool, str, str]] = []


def check(cond: bool, name: str, detail: str = "") -> None:
    _results.append((bool(cond), name, detail))


# 经典网络（可手算）：
#   A(3) → B(4) → D(2)
#   A(3) → C(2) → D(2)
# 总工期 9；关键路径 A-B-D；C 的时差 = 9-(3+2+2) = 2
TASKS = [
    {"id": 1, "wbs_code": "1.1", "name": "A 设计", "duration": 3, "owner_name": "张工"},
    {"id": 2, "wbs_code": "1.2", "name": "B 施工", "duration": 4, "owner_name": "李工"},
    {"id": 3, "wbs_code": "1.3", "name": "C 采购", "duration": 2, "owner_name": "王工"},
    {"id": 4, "wbs_code": "1.4", "name": "D 验收", "duration": 2, "owner_name": "赵工"},
]
EDGES = [
    {"pred": 1, "succ": 2, "dep_type": "FS", "lag": 0},
    {"pred": 1, "succ": 3, "dep_type": "FS", "lag": 0},
    {"pred": 2, "succ": 4, "dep_type": "FS", "lag": 0},
    {"pred": 3, "succ": 4, "dep_type": "FS", "lag": 0},
]

# ---------------------------------------------------------------- CPM 基准
cpm = compute_cpm([{"id": t["id"], "duration": t["duration"]} for t in TASKS], EDGES)
check(cpm["total"] == 9, "基准总工期 = 9 天", f"实际 {cpm['total']}")
check(cpm["critical"] == {1, 2, 4}, "关键任务是 A/B/D", f"实际 {sorted(cpm['critical'])}")
check(cpm["slack"][3] == 2, "C 的总时差 = 2 天", f"实际 {cpm['slack'][3]}")
check(cpm["es"][4] == 7 and cpm["ef"][4] == 9, "D 的 ES/EF = 7/9",
      f"{cpm['es'][4]}/{cpm['ef'][4]}")

# ---------------------------------------------------------------- 关键任务顺延
r = cie.simulate(TASKS, EDGES, [{"task_id": 2, "delay_days": 3, "type": "SHUTDOWN"}])
check(r["schedule_shift_days"] == 3, "关键任务顺延 3 天 → 总工期 +3", f"{r['schedule_shift_days']}")
check(r["adjusted"]["duration_days"] == 12, "调整后工期 12 天", f"{r['adjusted']['duration_days']}")
check(r["baseline_untouched"] is True, "结果声明未改动基线")
check(r["requires_approval"] is True, "结果要求人工审批")

# ---------------------------------------------------------------- 非关键任务在时差内
r2 = cie.simulate(TASKS, EDGES, [{"task_id": 3, "delay_days": 2, "type": "RESOURCE_CONFLICT"}])
check(r2["schedule_shift_days"] == 0, "非关键任务顺延 2 天（未超时差）→ 总工期不变",
      f"{r2['schedule_shift_days']}")
check("1.3" in r2["new_critical_tasks"], "C 被吃满时差后变为关键任务",
      f"{r2['new_critical_tasks']}")

# 超过时差则影响总工期
r3 = cie.simulate(TASKS, EDGES, [{"task_id": 3, "delay_days": 3, "type": "SHUTDOWN"}])
check(r3["schedule_shift_days"] == 1, "非关键任务顺延 3 天（超时差 1 天）→ 总工期 +1",
      f"{r3['schedule_shift_days']}")

# ---------------------------------------------------------------- 多情景累加
r4 = cie.simulate(TASKS, EDGES, [
    {"task_id": 2, "delay_days": 2, "type": "APPROVAL_DELAY"},
    {"task_id": 2, "delay_days": 3, "type": "SHUTDOWN"},
])
check(r4["schedule_shift_days"] == 5, "同一任务多个情景的顺延天数累加", f"{r4['schedule_shift_days']}")

# ---------------------------------------------------------------- 成本影响
r5 = cie.simulate(TASKS, EDGES, [{"task_id": 2, "delay_days": 4, "type": "SHUTDOWN"}],
                  daily_cost=1200)
check(r5["cost_impact"] == 4800, "成本影响 = 顺延天数 × 日成本", f"{r5['cost_impact']}")
r6 = cie.simulate(TASKS, EDGES, [{"task_id": 2, "delay_days": 4, "type": "SHUTDOWN"}])
check(r6["cost_impact"] is None, "未提供日成本时不出成本数字（不猜）", f"{r6['cost_impact']}")

# ---------------------------------------------------------------- 受影响任务清单
r7 = cie.simulate(TASKS, EDGES, [{"task_id": 2, "delay_days": 3, "type": "SHUTDOWN"}])
rows = {x["task_id"]: x for x in r7["affected_tasks"]}
check(4 in rows and rows[4]["change_kind"] == "FINISH_SHIFT", "下游任务 D 被标记为完工顺延",
      f"{rows.get(4)}")
# C 的完工时间没变，只是时差从 2 天涨到 5 天——必须与"工期顺延"区分开，
# 否则读者会以为这条任务也要加人加钱。
check(3 in rows and rows[3]["change_kind"] == "FLOAT_GAINED",
      "并行任务 C 只体现为时差变化，不标记为工期顺延", f"{rows.get(3)}")
check(r7["schedule_shifted_count"] == 2, "真正发生完工顺延的任务为 2 个（B、D）",
      f"{r7['schedule_shifted_count']}")
direct = [x for x in r7["affected_tasks"] if x["direct_change"]]
check(len(direct) == 1 and direct[0]["task_id"] == 2, "直接变更任务被单独标记")

# ---------------------------------------------------------------- 里程碑
ms = [
    {"milestone_code": "M1", "milestone_name": "立项批复", "plan_date": "2026-08-08", "status": "ACHIEVED"},
    {"milestone_code": "M2", "milestone_name": "验收移交", "plan_date": "2027-03-01", "status": "PENDING"},
]
rm = cie.simulate(TASKS, EDGES, [{"task_id": 2, "delay_days": 10, "type": "SHUTDOWN"}],
                  milestones=ms)
m1, m2 = rm["milestones"]
check(m1["achieved"] is True and m1["projected_shift_days"] == 0,
      "已达成的里程碑不顺移（既成事实）", f"shift={m1['projected_shift_days']}")
check(m1["projected_date"] == "2026-08-08", "已达成里程碑的推定日期 = 原计划日期",
      f"{m1['projected_date']}")
check(m2["projected_shift_days"] == 10 and m2["projected_date"] == "2027-03-11",
      "未完成里程碑按顺延天数后移", f"{m2['projected_date']}")

# ---------------------------------------------------------------- 拒算
def rejects(name: str, **kw) -> None:
    args = {"tasks": TASKS, "edges": EDGES, "scenarios": [{"task_id": 2, "delay_days": 1}]}
    args.update(kw)
    try:
        cie.simulate(args.pop("tasks"), args.pop("edges"), args.pop("scenarios"), **args)
    except cie.ScenarioInputError:
        check(True, name)
        return
    except Exception as exc:  # noqa: BLE001
        check(False, name, f"抛了非预期异常 {exc!r}")
        return
    check(False, name, "本应拒算但返回了结果")


rejects("空 WBS → 拒算", tasks=[])
rejects("没有情景 → 拒算", scenarios=[])
rejects("引用不存在的任务 → 拒算", scenarios=[{"task_id": 999, "delay_days": 1}])
rejects("负顺延 → 拒算", scenarios=[{"task_id": 2, "delay_days": -1}])
rejects("顺延超过 365 天 → 拒算",
        scenarios=[{"task_id": 2, "delay_days": cie.MAX_DELAY_DAYS + 1}])
rejects("未知变更类型 → 拒算", scenarios=[{"task_id": 2, "delay_days": 1, "type": "MAGIC"}])
rejects("负日成本 → 拒算", daily_cost=-1)

# ---------------------------------------------------------------- 声明
last = cie.simulate(TASKS, EDGES, [{"task_id": 2, "delay_days": 1}])
check(last["assumptions"]["probabilistic_claim"] is False, "明确声明不输出延期概率")
check("不是延期概率预测" in last["assumptions"]["statement"], "结果附带口径声明")

fails = [x for x in _results if not x[0]]
print("=" * 88)
print("变更影响分析 · 金标准用例")
print("=" * 88)
for ok, name, detail in _results:
    print(("  ✔ " if ok else "  ✘ ") + name + (f"  ← {detail}" if detail and not ok else ""))
print("=" * 88)
print(f"结果：通过 {len(_results) - len(fails)} / 失败 {len(fails)} / 共 {len(_results)}")
print("=" * 88)
raise SystemExit(1 if fails else 0)
