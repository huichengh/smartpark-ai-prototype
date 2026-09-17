"""前端权限键 × 后端 RBAC 模块/动作 一致性校验。

本项目已经因为「前端权限键与后端模块名不一致」出过 3 次真 bug，
且都不会被 tsc / 冒烟测试发现（守卫恒为 false → 页面不可用或按钮不显示）：

  1. nav.ts 用 'agent'，实际模块是 'ai'   → AI 智能体菜单对所有角色消失
  2. App.tsx 用 module="agent"            → AI 页面显示「权限不足」
  3. App.tsx 用 module="service" 守 /operations，实际后端要求 property
                                          → 物业/安全人员进不去工单页

校验范围：
  - frontend/src/**/*.tsx 里的 can('module', 'ACTION')
  - frontend/src/config/nav.ts 里的 perm: ['module', 'VIEW']
  - frontend/src/App.tsx 里的 <RequirePerm module="..." action="...">
  - 后端 app/api/v1/*.py 里的 auth.require("module", "ACTION")

用法：python check_permissions.py
前置：后端需在 127.0.0.1:8010 运行（用于取权威模块/动作清单）。
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = 'http://127.0.0.1:8010/api'
BACKEND = Path(__file__).resolve().parent


def authoritative() -> tuple[set[str], set[str]]:
    """以后端 /system/me/permissions 为准取模块与动作清单。"""
    login = urllib.request.Request(
        f'{API}/auth/login',
        data=json.dumps({'username': 'admin', 'password': 'Park@2026'}).encode(),
        headers={'Content-Type': 'application/json'},
    )
    tok = json.load(urllib.request.urlopen(login))['access_token']
    me = json.load(urllib.request.urlopen(urllib.request.Request(
        f'{API}/system/me/permissions',
        headers={'Authorization': 'Bearer ' + tok})))
    mods = set(me['module_permissions'].keys())
    acts: set[str] = set()
    for v in me['module_permissions'].values():
        acts.update(v)
    return mods, acts


def scan_frontend() -> list[tuple[str, int, str, str, str]]:
    """返回 (文件, 行号, 模块, 动作, 来源说明)。"""
    out: list[tuple[str, int, str, str, str]] = []
    src = ROOT / 'frontend' / 'src'

    for f in src.rglob('*.tsx'):
        for i, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
            for m in re.finditer(r"can\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", line):
                out.append((f.name, i, m.group(1), m.group(2), "can()"))
            for m in re.finditer(
                r'<RequirePerm[^>]*?module="([^"]+)"(?:[^>]*?action="([^"]+)")?', line
            ):
                out.append((f.name, i, m.group(1), m.group(2) or 'VIEW', "RequirePerm"))
            # 多行写法：module 与 action 分处两行，单独抓 module=
            for m in re.finditer(r'module="([a-z_]+)"', line):
                if 'RequirePerm' in line or 'Route' in line:
                    out.append((f.name, i, m.group(1), 'VIEW', "RequirePerm(跨行)"))

    nav = src / 'config' / 'nav.ts'
    for i, line in enumerate(nav.read_text(encoding='utf-8').splitlines(), 1):
        m = re.search(r"perm:\s*\[\s*'([^']+)'\s*,\s*'([^']+)'\s*\]", line)
        if m:
            out.append(('nav.ts', i, m.group(1), m.group(2), "nav perm"))
    return out


def scan_backend() -> list[tuple[str, int, str, str]]:
    out = []
    for f in (BACKEND / 'app' / 'api' / 'v1').glob('*.py'):
        for i, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
            m = re.search(r'auth\.require\(\s*"([^"]+)"\s*,\s*"([^"]+)"', line)
            if m:
                out.append((f.name, i, m.group(1), m.group(2)))
    return out


def main() -> int:
    mods, acts = authoritative()
    print(f'后端权威模块 {len(mods)} 个，动作 {len(acts)} 个\n')

    problems = 0

    print('--- 前端引用校验 ---')
    for fname, line, mod, act, kind in scan_frontend():
        why = None
        if mod not in mods:
            why = f'模块不存在（后端无 "{mod}"）'
        elif act not in acts:
            why = f'动作不存在（后端无 "{act}"）'
        if why:
            problems += 1
            print(f'  !! {fname}:{line}  {kind}  {mod}:{act}  → {why}')
    if problems == 0:
        print('  OK 前端所有权限键均合法')
    else:
        print(f'  合计 {problems} 处非法')

    print('\n--- 后端引用校验 ---')
    bproblems = 0
    for fname, line, mod, act in scan_backend():
        why = None
        if mod not in mods:
            why = f'模块不存在（RBAC 无 "{mod}"）→ 除集团管理员外全部 403'
        elif act not in acts:
            why = f'动作不存在（"{act}"）'
        if why:
            bproblems += 1
            print(f'  !! {fname}:{line}  auth.require("{mod}", "{act}")  → {why}')
    if bproblems == 0:
        print('  OK 后端所有 auth.require 的模块/动作均合法')
    else:
        print(f'  合计 {bproblems} 处非法')

    total = problems + bproblems
    print('\n' + '=' * 70)
    print(f'权限键不一致：前端 {problems} 处，后端 {bproblems} 处')
    print('=' * 70)
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
