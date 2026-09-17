"""扫描数据库中的「枚举列存了中文标签」问题。

背景：本项目多次出现「库内存中文、代码按英文枚举比较」的静默 bug
（energy_type='电' 而代码里比较 "ELECTRICITY"），后果是统计恒为 0，
既不报错也不影响其它接口，人工很难发现。

判定规则：对列名以 _type/_status/_stage/_level/_method/_result/_action/
_source/_category/_kind/_scope 结尾的文本列，若该列存在取值且全部含中文，
则很可能是「展示标签被写进了枚举列」。

用法：python check_enum_columns.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import String, func, inspect, select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402

SUFFIXES = ('_type', '_status', '_stage', '_level', '_method',
            '_result', '_action', '_source', '_category', '_kind', '_scope')

CN = re.compile(r'[\u4e00-\u9fff]')


def main() -> int:
    insp = inspect(engine)
    findings: list[tuple[str, str, list[str]]] = []

    with SessionLocal() as db:
        for table in sorted(insp.get_table_names()):
            t = Base.metadata.tables.get(table)
            if t is None:
                continue
            for col in insp.get_columns(table):
                name = col['name']
                if not name.endswith(SUFFIXES) or not isinstance(col['type'], String):
                    continue
                column = t.c.get(name)
                if column is None:
                    continue
                try:
                    rows = db.execute(
                        select(column, func.count()).group_by(column)
                    ).all()
                except Exception:
                    continue
                vals = [str(v) for v, _ in rows if v is not None and str(v) != '']
                if vals and all(CN.search(v) for v in vals):
                    findings.append((table, name, vals))

    print('=' * 74)
    print('枚举列中文值扫描（可能造成统计静默归零）')
    print('=' * 74)
    if not findings:
        print('OK 未发现「枚举列全部为中文」的列')
        return 0
    for table, col, vals in findings:
        sample = ', '.join(vals[:8]) + (' …' if len(vals) > 8 else '')
        print(f'!! {table}.{col}  ({len(vals)} 种取值)')
        print(f'      {sample}')
    print('-' * 74)
    print(f'共 {len(findings)} 个可疑列')
    return 1


if __name__ == '__main__':
    sys.exit(main())
