"""Qwen（或任何 OpenAI 兼容端点）接入层。

设计原则（和项目其它地方一致）：

1. **数字不交给模型**。模型只能"选工具、组织语言"，所有金额/比率/日期来自
   `call_tool()` 的真实返回。模型若在正文里编了数字，`_block` 的关键数据仍然
   使用工具结果，不会被覆盖。
2. **失败必须退回规则模式**。超时、断网、返回格式不对，一律抛异常由上层捕获，
   回落到 `orchestrator.answer()`，演示不会开天窗。
3. **同一套提示词，本地与云端通用**。默认指向 Ollama 的 OpenAI 兼容端点，
   改三个环境变量就能切到 DashScope / 硅基流动 等云端服务。

环境变量：
    AGENT_MODE=auto|llm|rule     auto=优先大模型，失败回落规则；rule=只用规则
    LLM_BASE_URL                 默认 http://127.0.0.1:11434/v1（Ollama）
    LLM_API_KEY                  本地可留空
    LLM_MODEL                    默认 qwen3.6:8b
    LLM_TIMEOUT                  单次请求超时秒数，默认 30
"""
from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from app.agent.tools import TOOL_REGISTRY, call_tool
from app.core.config import settings
from app.core.security import AuthContext

MAX_TOOL_ROUNDS = 4
MAX_TOOLS_IN_PROMPT = 25


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
def config() -> dict[str, Any]:
    """唯一来源是 app.core.config.settings。

    这里不再单独读环境变量：之前两处各读一次，默认值还不一样（config 是 rule、
    这里是 auto），排查起来会很费劲。改配置只改 config.py 一处。
    """
    return {
        "mode": (settings.AGENT_MODE or "rule").lower(),
        "base_url": (settings.LLM_BASE_URL or "").rstrip("/"),
        "api_key": settings.LLM_API_KEY or "not-needed",
        "model": settings.LLM_MODEL or "qwen3.6:8b",
        "timeout": float(settings.LLM_TIMEOUT or 30),
    }


def enabled() -> bool:
    """是否启用大模型路径。rule 模式下永远走规则。"""
    return config()["mode"] in ("auto", "llm") and bool(config()["base_url"])


def is_forced_llm() -> bool:
    """llm 模式表示"只用大模型"（失败也报错），auto 模式失败可回落。"""
    return config()["mode"] == "llm"


# --------------------------------------------------------------------------
# 工具 schema：从函数签名生成，避免手工维护 25 份 JSON
# --------------------------------------------------------------------------
_PY2JSON = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def _annotation_to_schema(ann: Any) -> dict[str, Any]:
    if ann is inspect.Parameter.empty:
        return {"type": "string"}
    # Optional[int] / int | None
    origin = getattr(ann, "__origin__", None)
    if origin is not None:
        args = [a for a in getattr(ann, "__args__", ()) if a is not type(None)]
        if args:
            return _annotation_to_schema(args[0])
        return {"type": "object"}
    base = _PY2JSON.get(ann)
    if base:
        return {"type": base}
    name = str(getattr(ann, "__name__", "")).lower()
    if name in ("int", "float", "str", "bool"):
        return {"type": _PY2JSON.get({"int": int, "float": float, "str": str, "bool": bool}[name], "string")}
    return {"type": "string"}


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def pick_tool_names(question: str, limit: int = 8) -> list[str]:
    """按问题相关度挑工具。

    25 个工具的 schema 全塞给 4B 模型，光提示词就要处理上千 token——
    在 CPU 上直接吃到超时。这里先用字二元组算重合度，只把最相关的几个给模型，
    既快也不会让模型在二十多个函数里选错。
    """
    q = _bigrams(question)
    scored: list[tuple[float, str]] = []
    for name, entry in TOOL_REGISTRY.items():
        text = f"{name} {entry.get('description') or ''} {' '.join(entry.get('tables') or [])}"
        overlap = len(q & _bigrams(text))
        # 名字里直接出现问题关键词的，额外加权
        bonus = sum(1 for w in q if len(w) == 2 and w in name)
        scored.append((overlap + bonus * 2, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = [n for score, n in scored[:limit] if score > 0]
    return picked or [n for _, n in scored[:limit]]


def tool_schemas(limit: int = MAX_TOOLS_IN_PROMPT,
                 names: list[str] | None = None) -> list[dict[str, Any]]:
    """把注册表里的工具转成 OpenAI function calling 定义。

    跳过 `db` / `auth`（由 call_tool 注入）和 `kw`（原始问句，由我们透传）：
    这些都该由运行时决定，让模型填只会增加填错的概率。
    """
    out: list[dict[str, Any]] = []
    picked = [(k, TOOL_REGISTRY[k]) for k in (names or list(TOOL_REGISTRY)) if k in TOOL_REGISTRY]
    for name, entry in picked[:limit]:
        fn: Callable = entry["fn"]
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname in ("db", "auth", "kw"):
                continue
            props[pname] = _annotation_to_schema(param.annotation)
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": (entry.get("description") or name)[:500],
                "parameters": {"type": "object", "properties": props,
                               "required": required},
            },
        })
    return out


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _post(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = config()
    url = f"{cfg['base_url']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"] and cfg["api_key"] != "not-needed":
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    with httpx.Client(timeout=cfg["timeout"]) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _chat(messages: list[dict], tools: list[dict] | None = None,
          temperature: float = 0.2) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config()["model"],
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    # Ollama 专有字段：让模型在多轮之间常驻内存，否则每次都要重新加载（CPU 上要几十秒）
    if "11434" in config()["base_url"]:
        payload["keep_alive"] = "30m"
    return _post(payload)


SYSTEM_PROMPT = """你是"园智汇 ParkOS"的园区经营助手。你可以调用平台提供的工具来读取真实业务数据。

铁律：
1. 任何数字（金额、面积、比率、天数、数量）只能来自工具返回，不得自己估算或编造。
2. 如果工具没有返回需要的数据，直接说明"数据不足"，不要用常识补全。
3. 不确定就用工具查；不要凭想象描述园区的现状。
4. 回答用中文，简洁、具体，不说套话。
5. 工具结果都在 data 字段里。若第一次调用的工具没有给出所需数据，
   换一个更对口的工具继续调用，不要直接回答"数据不足"。
6. 问经营总览类指标（出租率、收缴率、工单完成率、企业数等），
   优先用 get_dashboard_summary；问空置与招商方案用 get_space_status / get_operating_metrics。
"""

JSON_PROMPT = """基于上面工具返回的真实数据，输出一个 JSON（不要加代码围栏，不要多余文字），字段：
{
  "结论": "一句话结论，必须包含至少一个来自工具的具体数字",
  "关键数据": [{"label": "指标名", "value": "数值", "unit": "单位"}],
  "原因分析": ["..."],
  "建议措施": ["..."],
  "影响范围": "一句话",
  "风险": ["..."],
  "责任部门/角色": ["..."],
  "决策状态": "只能是 INFO、AI_SUGGESTION、NEED_CONFIRM、NEED_APPROVAL 之一"
}
要求：所有数字必须来自工具返回；数据不足时在"结论"里直说，不要编。"""


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def _strip_json(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start >= 0 and end > start else t


def _numbers_in(text: str) -> set[str]:
    """抽出文本里的数字（保留两位以内小数），用于与工具返回比对。"""
    out: set[str] = set()
    for m in re.findall(r"\d+(?:\.\d{1,2})?", text or ""):
        out.add(m.rstrip("."))
    return out


def check_numbers_grounded(conclusion: str, tool_text: str) -> tuple[bool, list[str]]:
    """校验结论里的数字是否都能在工具返回中找到。

    本地 3B 模型实测会把工具返回的 82.35% 写成 0%——这类错误比"慢"严重得多：
    整个平台的可信度就建立在"数字有出处"上。凡是结论里出现工具没有的数字，
    一律判定为不可信，由调用方回退到规则回答。
    """
    if not conclusion:
        return True, []

    allowed = _numbers_in(tool_text)
    bad: list[str] = []
    for n in _numbers_in(conclusion):
        if n not in allowed:
            bad.append(n)

    # 光比数字不够：库里"延期项目=0 个"会让结论里的"出租率 0%"蒙混过关。
    # 带百分号的结论数字，必须在工具返回里也以百分号形式出现。
    for n in set(re.findall(r"(\d+(?:\.\d{1,2})?)\s*%", conclusion or "")):
        if f"{n}%" not in re.sub(r"\s+", "", tool_text or ""):
            bad.append(f"{n}%")
    return (not bad), sorted(set(bad))


def compact_result(result: dict[str, Any], limit: int = 4000) -> str:
    """把工具返回压成模型读得懂的短文。

    工具结果是给前端渲染用的，字段多、嵌套深（图表数据动辄上万字符）。
    原样塞给 3B/4B 模型，它既读不完也读不准，往往直接答"数据不足"。
    这里优先抽出 kpis / 关键计数字段，其余按需截断。
    """
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        kpis = data.get("kpis")
        if isinstance(kpis, list) and kpis:
            parts = []
            for k in kpis:
                if not isinstance(k, dict):
                    continue
                label = k.get("label") or k.get("key")
                val = k.get("value")
                if val is None:
                    continue
                parts.append(f"{label}={val}{k.get('unit') or ''}")
            if parts:
                return "关键指标：" + "；".join(parts)

        # 无 kpis 时，收窄成顶层若干标量字段 + 数组长度，避免整棵子树
        brief: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                brief[k] = v
            elif isinstance(v, list):
                brief[k] = f"[{len(v)} 条]" + (
                    f" 首条：{json.dumps(v[0], ensure_ascii=False, default=str)[:200]}" if v else ""
                )
            elif isinstance(v, dict):
                brief[k] = f"{{{len(v)} 个字段}}"
        if brief:
            return json.dumps(brief, ensure_ascii=False, default=str)[:limit]

    if result.get("error"):
        return f"工具执行失败：{result['error']}"
    return json.dumps(result, ensure_ascii=False, default=str)[:limit]


def run(db: Session, auth: AuthContext, question: str,
        park_id: int | None = None) -> dict[str, Any]:
    """执行一次带工具调用的问答。

    返回结构与 orchestrator 的 route 结果保持一致，便于上层统一落库。
    任何异常都会抛出，由调用方回落到规则模式。
    """
    from app.agent.orchestrator import DecisionStatus, _block

    tools = tool_schemas(names=pick_tool_names(question))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    used: list[dict[str, Any]] = []       # 记录每次工具调用，供 evidence 用
    tool_payloads: list[dict[str, Any]] = []
    tool_payloads_text: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        data = _chat(messages, tools)
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            # 模型不再调工具 → 进入成文阶段
            messages.append({"role": "assistant", "content": msg.get("content") or ""})
            break

        messages.append(msg)
        for call in calls:
            fname = (call.get("function") or {}).get("name")
            raw_args = (call.get("function") or {}).get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            # kw 是工具内部的关键词参数，直接透传原始问句；
            # park_id 由当前页面上下文决定，不让模型猜。
            args.setdefault("kw", question)
            if park_id is not None:
                args.setdefault("park_id", park_id)
            try:
                result = call_tool(fname, db, auth, **args)
            except Exception as exc:  # noqa: BLE001
                result = {"error": f"工具执行失败：{exc}", "tool_error": True}
            used.append({"tool": fname, "args": args,
                         "ok": not result.get("tool_error")})
            tool_payloads.append(result)
            tool_payloads_text.append(compact_result(result))
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": compact_result(result),
            })

    messages.append({"role": "system", "content": JSON_PROMPT})
    data = _chat(messages, tools=None)
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    try:
        parsed = json.loads(_strip_json(content))
    except json.JSONDecodeError:
        parsed = {"结论": content.strip()[:300] or "模型未返回可解析的内容。"}

    # 模型可能返回我们没定义的状态名，必须收敛到真实枚举，
    # 否则 _block 会带着一个非法值落库，前端展示时对不上。
    allowed = {x.value: x.value for x in DecisionStatus}
    raw_decision = str(parsed.get("决策状态") or "").strip()
    decision = raw_decision if raw_decision in allowed else DecisionStatus.INFO.value

    # 数字校验：结论里的每个数字都必须在工具返回里出现过，否则整段不可信
    grounded, bad_numbers = check_numbers_grounded(
        str(parsed.get("结论") or ""), "\n".join(tool_payloads_text))
    if not grounded:
        raise ValueError(f"模型结论含工具未返回的数字：{bad_numbers}，已回落规则回答")

    key_data = [d for d in (parsed.get("关键数据") or []) if isinstance(d, dict)]
    block = _block(
        conclusion=str(parsed.get("结论") or "（模型未给出结论）"),
        key_data=key_data,
        reasons=[str(x) for x in (parsed.get("原因分析") or [])],
        suggestions=[str(x) for x in (parsed.get("建议措施") or [])],
        impact=str(parsed.get("影响范围") or ""),
        risks=[str(x) for x in (parsed.get("风险") or [])],
        owners=[str(x) for x in (parsed.get("责任部门/角色") or [])],
        decision=decision,
        data_sufficient=bool(tool_payloads),
        missing=[] if tool_payloads else ["未调用到任何工具，回答缺少数据支撑"],
    )

    return {
        "agent_key": "llm",
        "agent_name": f"大模型（{config()['model']}）",
        "intent": "llm",
        "response": block,
        "evidence": {
            "data_source": "平台业务数据库（经工具调用）",
            "tool_calls": used,
            "model": config()["model"],
            "endpoint": config()["base_url"],
            "data_label": "演示数据",
        },
        "model_mode": "llm",
    }


def daily_insight(items: list[dict[str, Any]]) -> dict[str, Any]:
    """让模型基于当天洞察条目写"今日结论 + 建议"。

    注意这里**不再调工具**：条目本身已经是工具产出的结果，
    模型只做归纳与措辞，避免为了写一段话再跑一遍全量取数。
    """
    compact = [{
        "标题": i.get("title"),
        "详情": (i.get("detail") or "")[:140],
        "级别": i.get("level"),
        "已有建议": i.get("suggestion"),
    } for i in items[:8]]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "以下是系统今天生成的洞察条目（JSON）：\n"
            + json.dumps(compact, ensure_ascii=False)
            + "\n\n请写一段今日经营结论（不超过 80 字，点名最关键的一条，"
              "不得出现条目里没有的数字），并给 3 条以内可执行建议。"
              "只输出 JSON：{\"结论\": \"...\", \"建议\": [\"...\"]}"
        )},
    ]
    data = _chat(messages, tools=None, temperature=0.3)
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    try:
        return json.loads(_strip_json(content))
    except json.JSONDecodeError:
        return {"结论": content.strip()[:120]}


def status() -> dict[str, Any]:
    """连通性自检：给前端/运维一个"模型到底通没通"的明确答复。"""
    cfg = config()
    info: dict[str, Any] = {
        "mode": cfg["mode"], "model": cfg["model"], "base_url": cfg["base_url"],
        "enabled": enabled(), "reachable": False, "error": None,
        "tool_count": len(TOOL_REGISTRY),
    }
    if not enabled():
        info["error"] = "AGENT_MODE=rule，未启用大模型"
        return info
    try:
        data = _post({
            "model": cfg["model"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        })
        info["reachable"] = bool(data.get("choices"))
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return info
