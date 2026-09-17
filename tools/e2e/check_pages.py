#!/usr/bin/env python
"""解析 gen_tour2.py 产出的 batch 输出，输出页面健康报告。

为什么需要它（旧探针为什么会漏）
    旧 gen_batch.py 用 document.body.innerText 的长度判断页面是否"有内容"，
    而侧边栏 20 个菜单 + 顶栏文字本身就有 1000+ 字，于是：
      · 合同管理页渲染抛错、<main> 完全为空 → 被判为健康
      · 安全页在"全部园区"下所有 KPI 都是 0/— → 被判为健康
    新探针只统计 <main> 的正文字数，并识别几种典型空数据态，
    本脚本据此给出 FAIL / WARN / OK。

判定
    FAIL : ERROR_TEXT / NEARLY_EMPTY（主内容区几乎没有内容）/ 页面异常
    WARN : STILL_LOADING / BAD_PLACEHOLDER（undefined、NaN）/ ALL_DASH（KPI 全是占位符）
    OK   : 其余

用法
    python check_pages.py tour4.out
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FAIL_FLAGS = {"ERROR_TEXT", "NEARLY_EMPTY"}
WARN_FLAGS = {"STILL_LOADING", "BAD_PLACEHOLDER", "ALL_DASH"}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "tour4.out")
    raw = path.read_text(encoding="utf-8", errors="replace")

    # batch 输出里每个探针结果都是一行 JSON（被 repr 包成字符串）
    pages: list[tuple[str, dict]] = []
    label = None
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^"@@PAGE (\S+) (.+)"$', line)
        if m:
            label = f"{m.group(1)} {m.group(2)}"
            continue
        if label and line.startswith('"') and "len" in line and "flags" in line:
            try:
                payload = json.loads(json.loads(line))
            except Exception:
                continue
            pages.append((label, payload))
            label = None

    # 页面级 JS 异常：batch 里表现为连续的 "✗ " 行
    page_errors = len(re.findall(r'^✗', raw, re.M))

    fails, warns, oks = [], [], 0
    for name, p in pages:
        flags = set(p.get("flags") or [])
        bad = flags & FAIL_FLAGS
        if bad:
            fails.append((name, sorted(bad), p.get("len"), p.get("head")))
        elif flags & WARN_FLAGS:
            warns.append((name, sorted(flags & WARN_FLAGS), p.get("len"), p.get("head")))
        else:
            oks += 1

    print("=" * 96)
    print(f"页面健康报告 · {path.name}")
    print("=" * 96)
    for name, p in pages:
        flags = set(p.get("flags") or [])
        if flags & FAIL_FLAGS:
            mark = "FAIL"
        elif flags & WARN_FLAGS:
            mark = "WARN"
        else:
            mark = "OK  "
        print(f"  [{mark}] {name:26} 正文 {p.get('len'):>5} 字  占位符 {p.get('dash'):>3}"
              f"  {','.join(sorted(flags)) or '-'}")
        if flags & (FAIL_FLAGS | WARN_FLAGS):
            print(f"          {str(p.get('head'))[:130]}")

    print("-" * 96)
    print(f"页面健康：{oks} OK / {len(warns)} WARN / {len(fails)} FAIL / 共 {len(pages)} 页"
          f"；页面级 JS 异常 {page_errors} 条")
    print("=" * 96)
    return 1 if (fails or page_errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
