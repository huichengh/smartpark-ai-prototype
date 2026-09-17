"""修复存量政策数据：把 Policy.conditions 从纯字符串迁移为结构化条件字典。

背景
    Policy.conditions 声明为 JSON 列，但早期 seeder 写入的是说明性字符串
    （"符合适用行业与规模条件，且注册地及主要经营场所在园区内。"）。
    agent 工具 _match_policy() 执行 cond.get(...) 时抛 AttributeError，
    被 call_tool 吞成"数据不足"，导致：
      · 政策AI 对任何提问都回答"当前数据不足以进行政策匹配"
      · 驾驶舱「AI 今日洞察」的政策机会条目从未出现
      · 企业详情页的政策匹配结果为空
    页面看起来"没有数据"，实际是数据格式与消费方契约不一致。

用法
    python migrate_policy_conditions.py --dry-run    # 只看会改什么
    python migrate_policy_conditions.py              # 实际写入
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import select, text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Policy  # noqa: E402
from app.seed.seed_data import POLICY_LIBRARY  # noqa: E402

# 结构化条件以 seeder 的 POLICY_LIBRARY 为唯一数据源（索引 8 为条件 dict）
CONDITIONS_BY_CODE: dict[str, dict] = {
    f"PO{i + 1:03d}": row[8] for i, row in enumerate(POLICY_LIBRARY)
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    policies = list(db.scalars(select(Policy)).all())
    print(f"政策总数：{len(policies)}")

    changed = skipped = unknown = 0
    for p in policies:
        target = CONDITIONS_BY_CODE.get(p.policy_code)
        if target is None:
            unknown += 1
            print(f"  [跳过] {p.policy_code} {p.policy_name}：种子库中无对应条件定义")
            continue
        if p.conditions == target:
            skipped += 1
            continue
        before = type(p.conditions).__name__
        if not args.dry_run:
            p.conditions = dict(target)
            # 适用行业与匹配条件同源，一并纠正
            if target.get("industries"):
                p.applicable_industry = list(target["industries"])
        changed += 1
        print(f"  [改写] {p.policy_code} {p.policy_name}：conditions {before} → dict"
              f"（{len(target)} 项条件）")

    # subsidy_amount 原为 String 列，库里存的是 '300000.0' 文本；
    # 模型已改为 Float，存量值需按数值重新落库（SQLite 动态类型，CAST 即可）。
    if not args.dry_run:
        db.commit()
        db.execute(text("UPDATE policies SET subsidy_amount = CAST(subsidy_amount AS REAL) "
                        "WHERE subsidy_amount IS NOT NULL"))
        db.commit()

    fixed_subsidy = db.execute(text(
        "SELECT COUNT(*) FROM policies WHERE typeof(subsidy_amount) = 'text'")).scalar() if not args.dry_run else "-"

    if args.dry_run:
        print(f"\n[dry-run] 将改写 {changed} 条，已合规 {skipped} 条，未匹配 {unknown} 条；未写入数据库。")
    else:
        print(f"\n[完成] 已改写 {changed} 条，已合规 {skipped} 条，未匹配 {unknown} 条；"
              f"subsidy_amount 仍为文本的行数：{fixed_subsidy}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
