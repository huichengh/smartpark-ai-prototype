#!/usr/bin/env python
"""生成按角色巡检的 agent-browser batch 脚本（多租户数据权限验证）。

对每个演示账号：清空登录态 -> 登录 -> 逐个访问其可见页面，
检查是否出现「权限不足 / 加载失败」以及正文是否为空。

用法：
  python gen_role_batch.py <用户名> <密码> <输出文件> [路由...]
"""
import json
import sys
from pathlib import Path

BASE = 'http://127.0.0.1:4173'

# 每个角色的关注点不同：园区负责人看运营全貌，企业管理员只看本企业
ROLE_ROUTES = {
    'p1_manager': ['/dashboard', '/twin', '/space', '/leasing', '/enterprise',
                   '/contracts', '/finance', '/projects', '/operations',
                   '/energy', '/safety', '/parking', '/meeting', '/approval',
                   '/ai', '/data', '/report', '/notification', '/audit', '/system'],
    'tenant1': ['/dashboard', '/contracts', '/finance', '/enterprise',
                '/parking', '/notification', '/ai', '/operations'],
}

PROBE = (
    "(function(){var t=document.body.innerText||'';var f=[];"
    "if(/权限不足/.test(t))f.push('FORBIDDEN');"
    "if(/出错|加载失败|请求失败|Cannot read/.test(t))f.push('ERROR_TEXT');"
    "if(/正在加载|加载中…/.test(t))f.push('STILL_LOADING');"
    "if(t.length<260)f.push('NEARLY_EMPTY');"
    "if(/undefined|NaN|\\[object Object\\]|null/.test(t))f.push('BAD_PLACEHOLDER');"
    "return JSON.stringify({len:t.length,flags:f});})()"
)


def main() -> int:
    user, pwd, out = sys.argv[1], sys.argv[2], sys.argv[3]
    routes = sys.argv[4:] or ROLE_ROUTES.get(user, ['/dashboard'])
    cmds: list[list[str]] = [
        ['open', BASE + '/login'],
        ['wait', '1500'],
        # 清掉可能残留的登录态，确保从零登录
        ['eval', "localStorage.clear();sessionStorage.clear();'cleared'"],
        ['open', BASE + '/login'],
        ['wait', '1500'],
        ['fill', "input[placeholder='请输入用户名']", user],
        ['fill', "input[placeholder='请输入密码']", pwd],
        ['click', 'button[type=submit]'],
        ['wait', '4000'],
        ['eval', "'@@LOGIN '+location.pathname"],
    ]
    for r in routes:
        cmds.append(['errors', '--clear'])
        cmds.append(['console', '--clear'])
        cmds.append(['open', BASE + r])
        cmds.append(['wait', '3000'])
        cmds.append(['eval', f"'@@PAGE {r}'"])
        cmds.append(['eval', PROBE])
        cmds.append(['errors'])
        cmds.append(['console'])

    Path(out).write_text(json.dumps(cmds, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{user}: 已生成 {out}（{len(routes)} 个路由）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
