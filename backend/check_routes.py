"""前端 API 路径 vs 后端 openapi 路由 交叉校验。

背景：前端 modules.ts 里的 URL 是字符串拼接，拼错了 tsc 不会报错，
      冒烟测试也只覆盖后端自身。此脚本把两边的「路径骨架」归一化后对比，
      找出前端调用了后端不存在的路由（运行时必然 404）。

用法：python check_routes.py
前置：后端需在 127.0.0.1:8010 运行。
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES_TS = ROOT / 'frontend' / 'src' / 'api' / 'modules.ts'
OPENAPI = 'http://127.0.0.1:8010/openapi.json'


def norm(path: str) -> str:
    """把 /a/${x}/b 与 /a/{x}/b 归一成 /a/{}/b，便于骨架对比。"""
    path = re.sub(r'\$\{[^}]+\}', '{}', path)
    path = re.sub(r'\{[^}]+\}', '{}', path)
    path = re.sub(r'/+', '/', path)
    return path.rstrip('/') or '/'


def load_backend() -> set[str]:
    o = json.load(urllib.request.urlopen(OPENAPI))
    out = set()
    for p in o['paths']:
        if p.startswith('/api'):
            out.add(norm(p[4:]))
    return out


def load_frontend() -> list[tuple[str, int]]:
    """抓 `url` 里的模板串：'`/xxx/${id}/yyy`' 或 '/xxx'。"""
    src = MODULES_TS.read_text(encoding='utf-8')
    found = []
    for i, line in enumerate(src.splitlines(), 1):
        for m in re.finditer(r"`(/[^`]*)`|'(/[^']*)'", line):
            raw = m.group(1) or m.group(2)
            if raw.startswith('//') or raw.startswith('/http'):
                continue
            found.append((raw, i))
    return found


def main() -> int:
    be = load_backend()
    fe = load_frontend()
    bad = []
    for raw, line in fe:
        skeleton = norm(raw)
        # 拼接片段（如 '/items'）无法独立校验，跳过非 / 开头的整段
        if not skeleton.startswith('/'):
            continue
        if skeleton in be:
            continue
        # 允许「父路径 + 追加段」的写法：取第一个段判断模块是否存在
        first = '/' + skeleton.strip('/').split('/')[0] if skeleton.strip('/') else '/'
        candidates = [p for p in be if p.startswith(first + '/') or p.startswith(first + '{') or p == first]
        bad.append((raw, line, len(candidates)))

    print(f'后端路由 {len(be)} 条，前端引用 {len(fe)} 处')
    if not bad:
        print('OK 前端所有 API 路径均能在后端 openapi 中找到')
        return 0
    print(f'\n!! {len(bad)} 处疑似不匹配：')
    for raw, line, n in bad:
        tail = '（该模块下有 %d 条路由，可能缺具体子路径）' % n if n else '（该模块在后端完全不存在）'
        print(f'  modules.ts:{line}  {raw}  {tail}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
