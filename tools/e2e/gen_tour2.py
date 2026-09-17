#!/usr/bin/env python
"""生成「主内容区」页面巡检 batch。

与 gen_batch.py 的区别（也是它漏掉整页空白的原因）：
  旧探针取 document.body.innerText 的长度，而侧边栏 + 顶栏文字就能撑到 1000+ 字，
  于是「安全页面在"全部园区"下整页为 0」这种问题会被判为健康。
  新探针只取 <main> 的内容，并额外检测「KPI 全是占位符 —」这一典型空数据态。

用法：
  python gen_tour2.py                       # dev server 5173
  python gen_tour2.py http://127.0.0.1:4173 # 构建产物预览
"""
import json
import sys
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5173').rstrip('/')

ROUTES = [
    ('/dashboard', '数据驾驶舱'), ('/twin', '园区数字孪生'), ('/space', '空间资产管理'),
    ('/leasing', '招商运营管理'), ('/enterprise', '企业服务中心'), ('/contracts', '合同管理'),
    ('/finance', '财务与账单'), ('/projects', '项目管理中心'), ('/projects/1', '项目详情'),
    ('/operations', '物业运维'), ('/energy', '能源管理'), ('/safety', '安全管理'),
    ('/parking', '停车与通行'), ('/meeting', '会议室与活动'), ('/approval', '审批中心'),
    ('/ai', 'AI 智能体'), ('/data', '数据中心'), ('/report', '报表中心'),
    ('/notification', '消息通知'), ('/audit', '日志审计'), ('/system', '系统管理'),
]

PROBE = (
    "(function(){"
    "var m=document.querySelector('main')||document.body;"
    "var t=m.innerText||'';var c=t.replace(/\\s/g,'');var f=[];"
    "if(/出错|加载失败|请求失败|权限不足|Cannot read|Something went wrong/.test(t))f.push('ERROR_TEXT');"
    "if(/正在加载|加载中/.test(t))f.push('STILL_LOADING');"
    "if(c.length<140)f.push('NEARLY_EMPTY');"
    "if(/undefined|NaN|\\[object Object\\]/.test(t))f.push('BAD_PLACEHOLDER');"
    # 占位符只统计「KPI 区」（正文前 900 字）：表格里的空单元格显示 — 属正常展示。
    # 且只在 KPI 区**几乎没有数字**时才报——否则一个页面有几项真实指标、
    # 少数几项为空也会被误报成"整页无数据"。
    "var seg=t.slice(0,900);"
    "var d=(seg.match(/—/g)||[]).length;var nums=(seg.match(/[0-9]/g)||[]).length;"
    "if(d>=3&&nums<12)f.push('ALL_DASH');"
    "var dalld=(t.match(/—/g)||[]).length;"
    "if(t.indexOf('演示数据')<0)f.push('NO_DEMO_BADGE');"
    "return JSON.stringify({len:c.length,dashKpi:d,dash:dalld,flags:f,"
    "head:t.replace(/\\n/g,'|').slice(0,150)});"
    "})()"
)

cmds: list[list[str]] = [
    ['open', BASE + '/'], ['wait', '1500'],
    ['click', 'button[type=submit]'], ['wait', '3500'],
    ['eval', "'@@LOGIN ok'"],
]
# dev server 会对每个模块即时编译，多请求页面首屏实测可达 7s；
# 构建产物（4173）没有编译开销，但财务/驾驶舱等多请求页面仍需约 3–5s。
# 等待太短会把"慢"误报成 STILL_LOADING，所以两种环境分别给足。
WAIT_MS = '9000' if '5173' in BASE else '5500'
for path, label in ROUTES:
    cmds += [
        ['errors', '--clear'], ['console', '--clear'],
        ['open', BASE + path], ['wait', WAIT_MS],
        ['eval', f"'@@PAGE {path} {label}'"],
        ['eval', PROBE],
        ['errors'], ['console'],
    ]

out = Path(__file__).resolve().parent / 'tour2.json'
out.write_text(json.dumps(cmds, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'已生成 {out}（{len(ROUTES)} 页）')
