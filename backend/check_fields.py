"""静态校验：路由/服务中所有 `Model.attr` 引用必须与模型真实列名一致。

用法（在 backend 目录下）：
    python check_fields.py

背景：本项目模型字段名较多且部分与直觉不同（如 WbsItem.item_name 而非 wbs_name、
Space.status 枚举值是 RENTED 而非 LEASED、LeasingLead 没有 enterprise_id 而是
converted_enterprise_id）。凭记忆写字段会反复在运行期才报错，成本很高。
本脚本在写完后立刻做一次全量静态检查，把这类错误一次性暴露出来。

两项检查：
  1. 属性访问：`Model.attr` —— 直接比对列名。
  2. 字典字面量键：形如 `{... "field": x.field ...}` 中，若取值侧 x 是某个
     ORM 模型的查询结果，则 "field" 也必须是该模型的列名。
     典型漏网点：`{"is_demo": c.is_demo}` 中 value 先被改写，key 却仍留在字典里。
  3. 构造器关键字：`Model(...)` / `Model(attr=...)` 中的关键字必须是列名或关系名。
  4. Python 语法错误。

第 2、3 项是本脚本早期版本的盲区，导致多起「字典 key / 构造参数写错字段名」
直到运行期才暴露。现已补齐。
"""
from __future__ import annotations

import ast
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def collect_models() -> dict[str, set[str]]:
    """收集「模型类名 -> 合法属性集合」。

    只收录**真正的 ORM 模型**：必须同时具备 `__tablename__`、`__table__`
    且 `__table__` 是 SQLAlchemy 的 Table 实例。

    这里踩过一个坑：`from app import models as M` 后 `dir(M)` 里除了业务模型，
    还会混进模块导入进来的符号（如 sqlalchemy 自己导出的 `Permission`）。
    它身上也恰好带一个 `__table__`，于是被误当成「权限表」注册进模型集合，
    结果所有 `p.park_name`（p 是 Park）全被报成 `Permission.park_name` —— 几十条假报错。
    因此必须校验 `__table__` 的真实类型。
    """
    from sqlalchemy import Table

    from app import models as M

    valid: dict[str, set[str]] = {}
    for name in dir(M):
        obj = getattr(M, name)
        if not isinstance(obj, type):
            continue
        tbl = getattr(obj, "__table__", None)
        if not isinstance(tbl, Table):
            continue
        if not getattr(obj, "__tablename__", None):
            continue
        # 只收本模块定义的模型，排除外部导入的同名类
        if not getattr(obj, "__module__", "").startswith("app."):
            continue
        rels = {r.key for r in getattr(obj, "__mapper__").relationships} \
            if hasattr(obj, "__mapper__") else set()
        valid[name] = {c.name for c in tbl.columns} | rels | set(dir(obj))
    return valid


def _model_of(node: ast.AST, valid: dict[str, set[str]],
              aliases: dict[str, str] | None = None) -> str | None:
    """尝试推断某个表达式的类型是哪个 ORM 模型。

    支持：`Model` 名、`select(Model)`、以及链式查询
    `db.scalars(q.order_by(Park.park_code).all())`。

    链式查询是最常见的写法，也是最难静态推断的：
        q = select(Park)                       # q 只是个普通变量名
        rows = list(db.scalars(q.order_by(...)).all())
    这里 `q.order_by(...)` 的内层是 `Name('q')`，本身推不出类型。
    `aliases` 提供「变量名 -> 模型名」的反查表（由 _bindings 构建），
    使得 `q` 能被还原成 `Park`。
    """
    al = aliases or {}
    if isinstance(node, ast.Name):
        if node.id in valid:
            return node.id
        return al.get(node.id)
    if isinstance(node, ast.Subscript):          # list[Model] / dict[...]
        return _model_of(node.slice, valid, al)
    if isinstance(node, ast.Tuple) and node.elts:
        return _model_of(node.elts[0], valid, al)
    if isinstance(node, ast.Call):
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        # 查询构造：select(Model) / select(Model.x)
        if fname in ("select", "from_", "aliased"):
            for a in list(node.args):
                m = _model_of(a, valid, al)
                if m:
                    return m
        # 结果取值 / 链式方法：all / scalars / unique / list / order_by / where ...
        for a in list(node.args):
            m = _model_of(a, valid, al)
            if m:
                return m
        # 递归到「被调用的对象」：q.order_by(...) -> q
        if isinstance(fn, ast.Attribute):
            return _model_of(fn.value, valid, al)
        # 递归到被调用函数的实参：list(x) / scalars(x) 已由上面覆盖，
        # 其余如 func.count(...) 不进模型推断
    if isinstance(node, ast.ListComp):
        return _model_of(node.elt, valid, al)
    return None


def _bindings(scope: ast.AST, valid: dict[str, set[str]],
              fn_bound: dict[ast.AST, dict[str, str]],
              global_bound: dict[str, str]) -> tuple[dict[str, str], set[str]]:
    """收集某个作用域内「变量名 -> 模型名」的绑定，以及被遮蔽的模型名。

    现实写法几乎都是两段式：
        rows = db.scalars(select(Visitor)).all()
        ...
        return [{...} for v in rows]
    变量 `rows` 本身已能推断出 Visitor，但推导式里迭代的是 `rows`，
    若只看 `for v in rows` 的 iter 是个 Name，就断不出类型。

    **必须是作用域级的**：同一个变量名在不同函数里会指向不同模型，
    Web 层最典型的是 `p` ——
        def parks(...):      rows = select(Park);  [{...} for p in rows]     # p 是园区
        def permissions(...): rows = select(Permission); [{...} for p in rows]  # p 是权限
    若把整个文件揉成一个映射，后者会污染前者，产生几十条假报错。

    作用域内查找顺序：本函数绑定 -> 模块级绑定（如 `_LABELS` 这类查询结果缓存）。
    """
    bound: dict[str, str] = {}
    shadowed: set[str] = set()

    # 两遍扫描：先收 `q = select(Park)` 这类直接可推断的别名，
    # 再用它去解析 `rows = list(db.scalars(q.order_by(...)).all())` 这类链式表达式。
    # 顺序敏感：链式表达式依赖别名表，一遍扫描时会因为 q 还没登记而漏掉。
    pending: list[tuple[list[ast.expr], ast.AST]] = []

    def _record(targets: list[ast.expr], value: ast.AST) -> None:
        m = _model_of(value, valid, bound)
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            if t.id in valid:                 # 变量名与模型名同名 -> 不可信
                shadowed.add(t.id)
                bound.pop(t.id, None)
                continue
            if m:
                bound[t.id] = m

    def _collect(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return                      # 内层作用域，不属于这里
        if isinstance(node, (ast.ListComp, ast.SetComp,
                             ast.GeneratorExp, ast.DictComp)):
            return                      # 推导式自带作用域，for 目标不外泄
        if isinstance(node, ast.Assign):
            pending.append((node.targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pending.append(([node.target], node.value))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            pending.append(([node.target], node.iter))
        for child in ast.iter_child_nodes(node):
            _collect(child)

    roots: list[ast.AST]
    if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
        roots = list(scope.body)
    else:
        roots = [scope]
    for r in roots:
        _collect(r)

    # 反复迭代直到不再有新绑定（链式依赖通常 2 轮内收敛）
    for _ in range(4):
        before = len(bound)
        for targets, value in pending:
            _record(targets, value)
        if len(bound) == before:
            break

    # 先用模块级绑定打底，再用本作用域绑定覆盖
    merged = {k: v for k, v in global_bound.items() if k not in shadowed}
    merged.update(bound)
    return merged, shadowed


def _model_of_ext(node: ast.AST, valid: dict[str, set[str]],
                  bound: dict[str, str], shadowed: set[str]) -> str | None:
    """在 _model_of 基础上支持「已绑定变量」的反查，并尊重遮蔽。"""
    if isinstance(node, ast.Name) and node.id in shadowed:
        return None                      # 名字被局部变量占用，不可信
    return _model_of(node, valid, bound)


# 有意为之的「输出键名 != 列名」白名单：(文件相对路径片段, 键名, 实际列名)
# 这些是接口契约里刻意做的对外命名（比列名更贴近前端语义），不是笔误。
KEY_RENAMES = {
    ("api/v1/project.py", "assignee", "assignee_name"),
    ("agent/tools/__init__.py", "score", "match_score"),
    ("agent/tools/__init__.py", "level", "match_level"),
    ("agent/tools/__init__.py", "reason", "match_reason"),
}


def _is_intended_rename(path: str, key: str, col: str) -> bool:
    norm = path.replace("\\", "/")
    return any(norm.endswith(f) and k == key and c == col
               for (f, k, c) in KEY_RENAMES)


def scan(valid: dict[str, set[str]], root: str = "app") -> int:
    bad: list[tuple[str, int, str]] = []
    kwbad: list[tuple[str, int, str]] = []
    syntax: list[tuple[str, str]] = []
    loopbad: list[tuple[str, int, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dirpath, f)
            try:
                tree = ast.parse(io.open(p, encoding="utf-8").read())
            except (SyntaxError, ValueError) as exc:
                syntax.append((p, str(exc)))
                continue
            # 作用域级绑定：模块级 + 每个函数各自一份，避免跨函数串味
            global_bound, _gs = _bindings(tree, valid, {}, {})
            fn_bound: dict[ast.AST, tuple[dict[str, str], set[str]]] = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_bound[node] = _bindings(node, valid, {}, global_bound)

            # 1) 属性访问 Model.attr
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    mn = node.value.id
                    # `Model.__tablename__` 这类 dunder 是类级元数据而非列，
                    # 且 valid[mn] 里已含 dir(obj)，不必也不应做列名校验
                    if node.attr.startswith("__") and node.attr.endswith("__"):
                        continue
                    if mn in valid and node.attr not in valid[mn]:
                        bad.append((p, node.lineno, f"{mn}.{node.attr}"))

            # 3) 构造器关键字 Model(attr=...)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in valid):
                    mn = node.func.id
                    for kw in node.keywords:
                        if kw.arg and kw.arg not in valid[mn]:
                            kwbad.append((p, node.lineno, f"{mn}({kw.arg}=...)"))

            # 2) 字典字面量键：仅当 value 形如 `x.attr` 且 x 推断为某模型时才校验。
            #    必须限定 value 是 Attribute，否则会大面积误报 ——
            #    返回体里常见 `{"parks": db.scalar(select(func.count(Park.id)))}`
            #    这类「键是人写的业务标签、值是聚合表达式」的写法，
            #    此时 _model_of 能从 select(Park) 推出 Park，
            #    于是把 "parks" 误判成「Park 的列名」。
            #    另外还要排除「纯标签字典」：像血缘链路里的
            #      {"table": Space.__tablename__, "name": "空间单元", "rows": cnt(Space)}
            #    只有当字典里存在「键名 == 值属性名」的项时，
            #    才认定它是实体字段展平输出，否则键名不参与校验。
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                same = [(k, v) for k, v in zip(node.keys, node.values)
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Attribute)
                        and isinstance(v.value, ast.Name)
                        and _model_of(v.value, valid) == k.value]
                if not same:
                    continue
                for k, v in zip(node.keys, node.values):
                    if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                        continue
                    if not (isinstance(v, ast.Attribute)
                            and isinstance(v.value, ast.Name)):
                        continue          # 只看 `"k": x.attr` 形态
                    mv = _model_of(v.value, valid)
                    if not mv:
                        continue
                    if k.value not in valid[mv]:
                        if _is_intended_rename(p, k.value, v.attr):
                            continue
                        bad.append((p, getattr(k, "lineno", 0),
                                    f'"{k.value}" (应为 {mv} 的列名)'))

            # 4) 推导式内的字典键：`[{ "field": x.field } for x in rows]`
            #    此处 x 只是普通变量名，检查 2 无法从 value 推断类型，
            #    是「循环变量绑定在推导式里」这一最常见写法的盲区。
            for node in ast.walk(tree):
                if not isinstance(node, (ast.ListComp, ast.SetComp,
                                         ast.GeneratorExp, ast.DictComp)):
                    continue
                # 找到包含该推导式的最内层函数，取其作用域绑定
                scope2bind: dict[str, str] = global_bound
                scope2shadow: set[str] = set()
                best = None
                for fn, (fb, fs) in fn_bound.items():
                    if (fn.lineno <= node.lineno
                            and (fn.end_lineno or fn.lineno) >= node.lineno):
                        if best is None or fn.lineno > best.lineno:
                            best = fn
                            scope2bind, scope2shadow = fb, fs
                var2model: dict[str, str] = {}
                for gen in node.generators:
                    if not isinstance(gen.target, ast.Name):
                        continue
                    m = _model_of_ext(gen.iter, valid, scope2bind, scope2shadow)
                    if m:
                        var2model[gen.target.id] = m
                if not var2model:
                    continue
                targets: list[ast.AST] = []
                if isinstance(node, ast.DictComp):
                    targets.append(node.value)
                elif isinstance(node.elt, ast.Dict):
                    targets.append(node.elt)
                for t in targets:
                    if not isinstance(t, ast.Dict):
                        continue
                    # 只在「实体序列化」语境下校验键名：出现至少一个
                    # 「键名 == 值列名」的项（如 {"story_code": s.story_code}），
                    # 说明是把模型逐字段摊平输出。
                    # 否则视为展示型字典（如 {"sprint": s.sprint_name}），
                    # 键是人写的标签，不做校验。
                    same = [(kk, vv) for kk, vv in zip(t.keys, t.values)
                            if isinstance(kk, ast.Constant)
                            and isinstance(kk.value, str)
                            and isinstance(vv, ast.Attribute)
                            and isinstance(vv.value, ast.Name)
                            and var2model.get(vv.value.id)
                            and kk.value == vv.attr]
                    if not same:
                        continue
                    for k, v in zip(t.keys, t.values):
                        if not (isinstance(k, ast.Constant)
                                and isinstance(k.value, str)):
                            continue
                        if not (isinstance(v, ast.Attribute)
                                and isinstance(v.value, ast.Name)):
                            continue
                        mn = var2model.get(v.value.id)
                        if not mn:
                            continue
                        if v.attr not in valid[mn]:
                            loopbad.append((p, getattr(v, "lineno", 0),
                                            f"{mn}.{v.attr}"))
                        if k.value not in valid[mn]:
                            if _is_intended_rename(p, k.value, v.attr):
                                continue
                            bad.append((p, getattr(k, "lineno", 0),
                                        f'"{k.value}" (应为 {mn} 的列名)'))
                        if mn and k.value not in valid[mn]:
                            bad.append((p, getattr(k, "lineno", 0),
                                        f'"{k.value}" (应为 {mn} 的列名)'))

    for p, e in syntax:
        print(f"[语法错误] {p}: {e}")
    for p, ln, attr in sorted(set(bad)):
        print(f"[字段错误] {p}:{ln}  {attr}")
    for p, ln, kw in sorted(set(kwbad)):
        print(f"[构造参数错误] {p}:{ln}  {kw}")
    for p, ln, attr in sorted(set(loopbad)):
        print(f"[字段错误] {p}:{ln}  {attr}")

    print("-" * 60)
    print(f"语法错误 {len(syntax)} 处；"
          f"非法字段引用 {len(set(bad) | set(loopbad))} 处；"
          f"非法构造参数 {len(set(kwbad))} 处")
    return len(syntax) + len(set(bad) | set(loopbad)) + len(set(kwbad))


def check_routes() -> int:
    """路由检查：重复前缀（/a/a/...）与 path+method 冲突。

    背景：给 APIRouter 补 prefix 时，若路由函数内已写过同样前缀，
    会静默变成 /finance/finance/summary 这种「能启动但 404」的错误。
    """
    try:
        from app.main import app
    except Exception as exc:                    # noqa: BLE001
        print(f"[路由检查跳过] 应用加载失败：{exc}")
        return 1

    paths = app.openapi().get("paths", {})
    problems = 0

    for p in sorted(paths):
        segs = p.split("/")
        for i in range(len(segs) - 1):
            if segs[i] and segs[i] == segs[i + 1]:
                print(f"[双前缀路由] {p}  —— 前缀 {segs[i]!r} 重复")
                problems += 1
                break

    seen: dict[tuple[str, str], int] = {}
    for p, ops in paths.items():
        for m in ops:
            key = (p, m.upper())
            seen[key] = seen.get(key, 0) + 1
    for (p, m), n in seen.items():
        if n > 1:
            print(f"[路由冲突] {m} {p} 注册了 {n} 次")
            problems += 1

    print(f"路由问题 {problems} 处（共 {len(paths)} 条路径）")
    return problems


if __name__ == "__main__":
    total = scan(collect_models())
    print()
    total += check_routes()
    sys.exit(1 if total else 0)
