"""把 energy_records.energy_type 的历史中文值迁移为规范英文枚举值。

背景：seeder 早期写入「电」/「水」，而 dashboard_service / operation.py /
space.py / agent tools 共 8 处按 "ELECTRICITY" / "WATER" 比较，
导致能源模块所有统计恒为 0。seeder 已修正，存量数据需要本脚本一次性迁移。

幂等：重复执行不会产生副作用（已规范的行不会被再次写入）。

用法：python migrate_energy_type.py [--dry-run]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import EnergyRecord  # noqa: E402

# 中文标签 → 规范枚举值
MAPPING = {
    '电': 'ELECTRICITY', '电力': 'ELECTRICITY', '电耗': 'ELECTRICITY',
    '水': 'WATER', '用水': 'WATER',
    '气': 'GAS', '燃气': 'GAS', '天然气': 'GAS',
    '光伏': 'PV', '光伏发电': 'PV',
    '充电': 'CHARGING', '充电桩': 'CHARGING',
}

# 规范值对应的单位（顺带纠正常见的单位串写）
UNIT_FIX = {'ELECTRICITY': 'kWh', 'WATER': 'm³', 'GAS': 'm³',
            'PV': 'kWh', 'CHARGING': 'kWh'}


def main() -> int:
    dry = '--dry-run' in sys.argv
    changed = 0
    with SessionLocal() as db:
        for legacy, canonical in MAPPING.items():
            if legacy == canonical:
                continue
            rows = db.scalars(
                select(EnergyRecord).where(EnergyRecord.energy_type == legacy)
            ).all()
            if not rows:
                continue
            print(f'  {legacy!r:>8} → {canonical:<12} {len(rows):>5} 行')
            for r in rows:
                r.energy_type = canonical
                unit = UNIT_FIX.get(canonical)
                if unit and r.unit != unit:
                    r.unit = unit
            changed += len(rows)

        if dry:
            db.rollback()
            print(f'[dry-run] 将更新 {changed} 行，未提交')
            return 0
        db.commit()

        left = db.execute(
            select(EnergyRecord.energy_type, func.count())
            .group_by(EnergyRecord.energy_type)
        ).all()
        print(f'已更新 {changed} 行；迁移后取值分布：')
        for k, c in left:
            print(f'   {k}: {c}')
    return 0


if __name__ == '__main__':
    print('energy_type 存量数据迁移')
    sys.exit(main())
