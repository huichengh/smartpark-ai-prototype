"""对可疑列，检查代码里是否存在「用英文枚举与之比较」的地方。

check_enum_columns.py 找出「列值全是中文」的列后，本脚本进一步判断
这些列是否真有风险：只有当代码里出现 `xxx == "ENGLISH_TOKEN"` 或
`xxx in ("A","B")` 且右侧是 ASCII 大写枚举时，才是真 bug
（库内存中文 → 条件恒不成立 → 统计/筛选静默失效）。

用法：python check_enum_mismatch.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import String, func, inspect, select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402

APP = Path(__file__).resolve().parent / 'app'
SUFFIXES = ('_type', '_status', '_stage', '_level', '_method',
            '_result', '_action', '_source', '_category', '_kind', '_scope')
CN = re.compile(r'[\u4e00-\u9fff]')

# 列名 → 可能的属性访问写法（模型属性名与列名同名的按此处理）
def ascii_compare_hits(col: str) -> list[tuple[str, int, str]]:
    """在 app/ 下查找该列与 ASCII 大写枚举字面量比较的位置。"""
    attr = re.escape(col)
    # col == "TOKEN" / col != "TOKEN" / col in ("A","B")
    pats = [
        re.compile(rf'\b{attr}\s*(?:==|!=)\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(rf'\b{attr}\s+in\s*[\(\[]\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(rf'get\(\s*"{attr}"\s*\)\s*(?:==|!=)\s*"([A-Z][A-Z0-9_]*)"'),
    ]
    hits = []
    for f in APP.rglob('*.py'):
        try:
            lines = f.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for p in pats:
                m = p.search(line)
                if m:
                    hits.append((f.relative_to(APP.parent).as_posix(), i, m.group(1)))
    return hits


def main() -> int:
    insp = inspect(engine)
    suspects: list[tuple[str, str, list[str]]] = []

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
                    rows = db.execute(select(column, func.count()).group_by(column)).all()
                except Exception:
                    continue
                vals = [str(v) for v, _ in rows if v is not None and str(v) != '']
                if vals and all(CN.search(v) for v in vals):
                    suspects.append((table, name, vals))

    print('=' * 78)
    print('枚举列「中文存值 × 英文比较」风险判定')
    print('=' * 78)
    risky = []
    safe = []
    for table, col, vals in suspects:
        hits = ascii_compare_hits(col)
        if hits:
            risky.append((table, col, vals, hits))
        else:
            safe.append((table, col, vals))

    if risky:
        print(f'\n!! 高风险 {len(risky)} 列（代码里存在英文枚举比较）:')
        for table, col, vals, hits in risky:
            print(f'\n  {table}.{col}   库内存值: {"、".join(vals[:6])}')
            for f, i, tok in hits[:6]:
                print(f'      {f}:{i}  比较 "{tok}"')
            if len(hits) > 6:
                print(f'      …另有 {len(hits) - 6} 处')
    else:
        print('\nOK 未发现高风险列（其余列的中文取值即业务键，消费方一致）')

    print(f'\n-- 其余 {len(safe)} 列为「中文即业务键」（消费方也用中文，无风险）:')
    for table, col, vals in safe:
        print(f'   {table}.{col}  →  {"、".join(vals[:5])}')
    return 1 if risky else 0


if __name__ == '__main__':
    sys.exit(main())
