"""AI Agent 路由：主 Agent「园智AI总管」+ 11 个子 Agent + AI 项目经理。

统一输出格式（需求书第 36 节）：
  结论 / 关键数据 / 原因分析 / 建议措施 / 影响范围 / 风险 / 责任部门/角色 / 决策状态

权限三级（第 37 节）：
  L1 信息查询 → AI 直接回答
  L2 分析与建议 → AI 给建议，人工采纳
  L3 高影响动作 → AI 只生成审批请求，绝不自行执行
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.agent import orchestrator as orch
from app.core.audit import write_audit
from app.core.security import CurrentAuth, DbSession
from app.models import (
    AIConversation,
    AIMessage,
    AIRecommendation,
    ApprovalRequest,
    ApprovalStep,
)
from app.schemas.common import ChatRequest, paginate

router = APIRouter(prefix="/agent", tags=["AI 智能体"])

OUTPUT_SECTIONS = ["结论", "关键数据", "原因分析", "建议措施", "影响范围", "风险",
                   "责任部门/角色", "决策状态"]

PERMISSION_MODEL = {
    "L1": {"name": "信息查询", "desc": "AI 可直接读取数据并回答，不改变任何业务状态",
            "need_approval": False},
    "L2": {"name": "分析与建议", "desc": "AI 输出分析与建议，由人工决定是否采纳",
            "need_approval": False},
    "L3": {"name": "高影响动作", "desc": "AI 只能生成审批请求，必须人工审批后由人执行",
            "need_approval": True},
}


def _agent_list() -> list[dict[str, Any]]:
    out = []
    for key, a in orch.SUB_AGENTS.items():
        item = dict(a)
        # 关键词仅用于意图路由，不对外暴露，避免前端实现「关键词匹配」的伪 AI
        item.pop("keywords", None)
        out.append(item)
    return out


@router.get("/agents")
def list_agents() -> dict[str, Any]:
    """主 Agent 与全部子 Agent 的能力清单。"""
    from app.agent import tools as T

    out = []
    for key, a in orch.SUB_AGENTS.items():
        item = {k: v for k, v in a.items() if k != "keywords"}
        item["tool_count"] = len(a.get("tools", []))
        out.append(item)

    tools = []
    for name, meta in getattr(T, "TOOL_REGISTRY", {}).items():
        tools.append({
            "name": name,
            "description": meta.get("description") if isinstance(meta, dict) else str(meta),
            "params": meta.get("params") if isinstance(meta, dict) else None,
            "returns": "data + evidence + data_sufficient",
        })

    return {
        "main_agent": orch.MAIN_AGENT,
        "agents": out,
        "total": len(out),
        "permission_model": PERMISSION_MODEL,
        "output_format": OUTPUT_SECTIONS,
        "tool_count": len(tools),
        "tools": tools,
        "data_label": "演示数据",
    }


@router.post("/chat")
def chat(payload: ChatRequest, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """与 AI 对话：真实调用工具层读库 → 结构化回答 → 落库 + 审计。"""
    auth.require("ai", "AI")
    result = orch.answer(db, auth, payload.question,
                         park_id=payload.park_id, project_id=payload.project_id,
                         forced_agent=payload.agent_key)
    response = result.get("response") or {}

    now = dt.datetime.now()
    conv = None
    if payload.conversation_id:
        conv = db.get(AIConversation, payload.conversation_id)
        if conv and conv.user_id != auth.user.id:
            raise HTTPException(403, "无权写入他人会话")
    if conv is None:
        seq = (db.scalar(select(func.count(AIConversation.id))) or 0) + 1
        conv = AIConversation(
            conversation_code=f"CV{now:%Y%m%d}{seq:05d}",
            user_id=auth.user.id, title=payload.question[:40],
            agent_key=result.get("intent"), park_id=payload.park_id,
            message_count=0,
        )
        db.add(conv)
        db.flush()

    db.add(AIMessage(conversation_id=conv.id, role="user", content=payload.question,
                     created_at=now))
    msg = AIMessage(
        conversation_id=conv.id, role="assistant",
        content=_flatten(response),
        agent_key=result.get("intent"), agent_name=result.get("intent_label"),
        intent=result.get("intent"), structured=response,
        evidence=result.get("evidence"),
        permission_level=result.get("permission_level"),
        decision_status=(response.get("决策状态") if isinstance(response, dict) else None),
        tokens=None, latency_ms=result.get("latency_ms"),
        data_sufficient=result.get("data_sufficient", True),
        created_at=now,
    )
    db.add(msg)
    conv.message_count = (conv.message_count or 0) + 2
    conv.last_message_at = now
    conv.title = conv.title or payload.question[:40]
    db.flush()

    write_audit(db, module="ai", action="AI", auth=auth, object_type="AIMessage",
                object_id=msg.id, object_name=payload.question[:60],
                after_value={"agent_key": result.get("intent"),
                             "intent": result.get("intent"),
                             "permission_level": result.get("permission_level"),
                             "data_sufficient": result.get("data_sufficient")},
                change_summary=f"AI 问答：{payload.question[:60]}"
                               f"（Agent：{result.get('intent_label')}）",
                source="AI")
    db.commit()

    return {
        **result,
        "conversation_id": conv.id,
        "message_id": msg.id,
        "data_label": "演示数据",
    }


def _flatten(response: Any) -> str:
    """把结构化输出压成可搜索的纯文本，供列表与检索使用。"""
    if not isinstance(response, dict):
        return str(response)
    lines = []
    for k, v in response.items():
        if isinstance(v, list):
            parts = []
            for x in v:
                if isinstance(x, dict):
                    parts.append(f"{x.get('label', '')} {x.get('value', '')}{x.get('unit', '')}"
                                 + (f"（口径：{x['basis']}）" if x.get("basis") else ""))
                else:
                    parts.append(str(x))
            lines.append(f"【{k}】" + "；".join(parts))
        else:
            lines.append(f"【{k}】{v}")
    return "\n".join(lines)


@router.get("/conversations")
def list_conversations(db: DbSession, auth: CurrentAuth,
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("ai", "VIEW")
    rows = list(db.scalars(select(AIConversation).where(AIConversation.user_id == auth.user.id)
                           .order_by(AIConversation.last_message_at.desc().nullslast(),
                                     AIConversation.id.desc())).all())
    items = [{
        "id": c.id, "conversation_code": c.conversation_code, "title": c.title,
        "agent_key": c.agent_key, "park_id": c.park_id,
        "message_count": c.message_count,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    } for c in rows]
    return paginate(items, page, page_size)


@router.get("/conversations/{conversation_id}")
def conversation_detail(conversation_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("ai", "VIEW")
    c = db.get(AIConversation, conversation_id)
    if not c or (c.user_id != auth.user.id and not auth.is_group_admin):
        raise HTTPException(404, "会话不存在或无权访问")
    msgs = list(db.scalars(select(AIMessage).where(AIMessage.conversation_id == conversation_id)
                           .order_by(AIMessage.id)).all())
    return {
        "conversation": {"id": c.id, "conversation_code": c.conversation_code,
                         "title": c.title, "agent_key": c.agent_key,
                         "message_count": c.message_count},
        "messages": [{
            "id": m.id, "role": m.role, "content": m.content,
            "agent_key": m.agent_key, "agent_name": m.agent_name,
            "intent": m.intent, "structured": m.structured,
            "evidence": m.evidence, "permission_level": m.permission_level,
            "decision_status": m.decision_status, "data_sufficient": m.data_sufficient,
            "tokens": m.tokens, "latency_ms": m.latency_ms,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs],
        "data_label": "演示数据",
    }


def _rec_out(r: AIRecommendation) -> dict[str, Any]:
    """AIRecommendation 输出模型（字段与数据库模型一一对应，无虚构字段）。

    模型真实字段：rec_code / agent_key / category / title / summary / detail /
    severity / confidence / related_module / related_object_type /
    related_object_id / evidence / suggestion / action_label / action_route /
    permission_level / decision_status / status / generated_date / read_count
    """
    return {
        "id": r.id,
        "rec_code": r.rec_code,
        "agent_key": r.agent_key,
        "category": r.category,
        "title": r.title,
        "summary": r.summary,
        "detail": r.detail,
        "severity": r.severity,
        "confidence": r.confidence,
        "park_id": r.park_id,
        "related_module": r.related_module,
        "related_object_type": r.related_object_type,
        "related_object_id": r.related_object_id,
        "evidence": r.evidence,
        "suggestion": r.suggestion,
        "action_label": r.action_label,
        "action_route": r.action_route,
        "permission_level": r.permission_level,
        "decision_status": r.decision_status,
        "status": r.status,
        "read_count": r.read_count,
        "generated_date": (r.generated_date.isoformat()
                           if r.generated_date else None),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/recommendations")
def list_recommendations(db: DbSession, auth: CurrentAuth,
                         status: str | None = None, category: str | None = None,
                         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """AI 主动建议（每条都带证据链与决策状态）。"""
    auth.require("ai", "VIEW")
    vis = auth.visible_park_ids()
    q = select(AIRecommendation)
    if vis is not None:
        q = q.where(AIRecommendation.park_id.in_(vis)) if vis else q.where(AIRecommendation.id == -1)
    if status:
        q = q.where(AIRecommendation.status == status)
    if category:
        q = q.where(AIRecommendation.category == category)
    rows = list(db.scalars(q.order_by(AIRecommendation.created_at.desc())).all())
    items = [_rec_out(r) for r in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "pending": len([i for i in items if i["status"] in ("NEW", "PENDING")]),
        "adopted": len([i for i in items if i["status"] in ("ADOPTED", "PENDING_APPROVAL")]),
        "rejected": len([i for i in items if i["status"] == "REJECTED"]),
        "by_category": {k: len([i for i in items if i["category"] == k])
                        for k in {i["category"] for i in items}},
        "by_severity": {k: len([i for i in items if i["severity"] == k])
                        for k in {i["severity"] for i in items}},
        "needs_approval": len([i for i in items if i["permission_level"] == "L3"
                               and i["status"] in ("NEW", "PENDING")]),
    }
    return result


@router.post("/recommendations/{rec_id}/adopt")
def adopt_recommendation(rec_id: int, db: DbSession, auth: CurrentAuth,
                         note: str | None = None) -> dict[str, Any]:
    """采纳 AI 建议。

    L3 高影响建议不会被直接执行，而是转成「审批请求」——符合第 37 节要求：
    高风险动作必须人工审批，AI 不得自行执行。
    """
    auth.require("ai", "AI")
    r = db.get(AIRecommendation, rec_id)
    if not r:
        raise HTTPException(404, "建议不存在")
    if r.status not in ("NEW", "PENDING"):
        raise HTTPException(400, f"该建议当前状态为「{r.status}」，不可重复采纳")

    r.status = "ADOPTED"
    r.decision_status = "已采纳"
    if note:
        r.detail = (r.detail or "") + f"\n[采纳备注] {note}"

    approval_code = None
    if r.permission_level == "L3":
        now = dt.datetime.now()
        seq = (db.scalar(select(func.count(ApprovalRequest.id))) or 0) + 1
        ar = ApprovalRequest(
            approval_code=f"AP{now:%Y%m%d}{seq:05d}",
            approval_type=_approval_type_of(r.category),
            title=f"[AI建议转审批] {r.title}",
            park_id=r.park_id,
            related_object_type=r.related_object_type,
            related_object_id=r.related_object_id,
            content=(f"AI 建议：{r.title}\n{r.detail or r.summary or ''}\n"
                     f"建议措施：{r.suggestion or '未给出'}\n"
                     f"证据链：{r.evidence}"),
            ai_analysis=r.evidence,
            risk_level=r.severity,
            urgency="HIGH" if r.severity in ("HIGH", "CRITICAL") else "MEDIUM",
            status="PENDING", current_step=1, total_steps=2,
            applicant_id=auth.user.id, applicant_name=auth.user.real_name,
            apply_at=now, is_ai_generated=True, source="AI",
            remark=f"由 AI 建议 {r.rec_code} 转化的高影响动作，"
                   f"必须人工审批后方可执行（AI 不会自行执行）",
        )
        db.add(ar)
        db.flush()
        db.add(ApprovalStep(approval_id=ar.id, step_no=1, step_name="业务负责人复核",
                            approver_role="PARK_MANAGER", status="PENDING"))
        db.add(ApprovalStep(approval_id=ar.id, step_no=2, step_name="集团审批",
                            approver_role="GROUP_ADMIN", status="WAITING"))
        approval_code = ar.approval_code
        r.decision_status = "待审批"
        r.status = "PENDING_APPROVAL"
    elif r.permission_level == "L2":
        r.decision_status = "已采纳（分析建议）"
    else:
        r.decision_status = "已查阅（信息提示）"

    write_audit(db, module="ai", action="AI", auth=auth, object_type="AIRecommendation",
                object_id=r.id, object_name=r.rec_code,
                before_value={"status": "NEW"},
                after_value={"status": r.status, "approval_code": approval_code},
                change_summary=(f"采纳 AI 建议「{r.title}」"
                                + (f"，已转为审批单 {approval_code}"
                                   f"（L{r.permission_level[-1]} 高影响动作，需人工审批）"
                                   if approval_code else "（L2 分析建议，无需审批）")),
                source="AI")
    db.commit()
    return {
        "success": True,
        "message": (f"建议已采纳，并生成审批单 {approval_code}，须经人工审批后方可执行"
                    f"（AI 不执行高影响动作）"
                    if approval_code else "建议已采纳，请按建议措施落实"),
        "status": r.status, "decision_status": r.decision_status,
        "approval_code": approval_code, "permission_level": r.permission_level,
        "suggestion": r.suggestion, "action_label": r.action_label,
        "action_route": r.action_route,
    }


def _approval_type_of(category: str | None) -> str:
    m = {
        "招商": "CONTRACT", "合同": "CONTRACT", "财务": "PAYMENT", "催收": "PAYMENT",
        "空间": "SPACE", "企业": "ENTERPRISE", "项目": "CHANGE",
        "物业": "OTHER", "设备": "DEVICE_SCRAP", "能源": "OTHER",
        "安全": "OTHER", "政策": "POLICY",
    }
    return m.get(category or "", "OTHER")


@router.post("/recommendations/{rec_id}/reject")
def reject_recommendation(rec_id: int, db: DbSession, auth: CurrentAuth,
                          reason: str | None = None) -> dict[str, Any]:
    auth.require("ai", "AI")
    r = db.get(AIRecommendation, rec_id)
    if not r:
        raise HTTPException(404, "建议不存在")
    r.status = "REJECTED"
    r.decision_status = "已驳回"
    if reason:
        r.detail = (r.detail or "") + f"\n[驳回原因] {reason}"
    write_audit(db, module="ai", action="AI", auth=auth, object_type="AIRecommendation",
                object_id=r.id, object_name=r.rec_code,
                after_value={"status": "REJECTED"},
                change_summary=f"驳回 AI 建议「{r.title}」：{reason or '无说明'}",
                source="AI")
    db.commit()
    return {"success": True, "message": "建议已驳回"}


@router.get("/pm/{project_id}")
def ai_project_manager(db: DbSession, auth: CurrentAuth, project_id: int) -> dict[str, Any]:
    """AI 项目经理：项目体检 + 结构化输出（含证据链与决策状态）。"""
    auth.require("ai", "AI")
    from app.core.audit import write_audit as _wa
    from app.models import Project

    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    if not auth.can_access_park(p.park_id):
        raise HTTPException(403, "无权访问该项目数据")
    if not auth.can_access_project(project_id):
        raise HTTPException(403, "您的项目数据权限不包含该项目")

    result = orch.answer(db, auth, f"分析项目 {p.project_name} 的健康状况与风险",
                         project_id=project_id, forced_agent="project")
    _wa(db, module="ai", action="AI", auth=auth, object_type="Project",
        object_id=project_id, object_name=p.project_name,
        change_summary=f"AI 项目经理体检：{p.project_name}"
                       f"（数据充分性：{'充分' if result.get('data_sufficient') else '不足'}）",
        source="AI")
    db.commit()
    return {**result, "project": {"id": p.id, "project_code": p.project_code,
                                  "project_name": p.project_name,
                                  "management_method": p.management_method},
            "data_label": "演示数据"}


@router.get("/daily-insight")
def daily_insight(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """AI 今日洞察：跨模块汇总当日最值得关注的事项。"""
    auth.require("ai", "AI")
    items = orch.build_daily_insights(db, auth, park_id=park_id)
    sev_rank = {"CRITICAL": 0, "RISK": 1, "WARNING": 2, "INFO": 3}
    items.sort(key=lambda x: sev_rank.get(x.get("severity"), 9))
    return {
        "items": items,
        "total": len(items),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "severity_count": {k: len([i for i in items if i.get("severity") == k])
                           for k in ["CRITICAL", "RISK", "WARNING", "INFO"]},
        "basis": ("洞察由各业务模块阈值规则实时计算得出，每条均附带触发值、阈值与建议动作；"
                  "数据不足的模块会在 data_notes 中明确说明"),
        "data_label": "演示数据",
    }


@router.get("/tools")
def list_tools() -> dict[str, Any]:
    from app.agent import tools as T

    tools = []
    for name, meta in getattr(T, "TOOL_REGISTRY", {}).items():
        tools.append({
            "name": name,
            "description": meta.get("description") if isinstance(meta, dict) else str(meta),
            "params": meta.get("params") if isinstance(meta, dict) else None,
        })
    return {
        "tools": tools,
        "total": len(tools),
        "note": "所有工具均返回 data + evidence + data_sufficient 三部分；"
                "AI 回答必须基于工具返回的真实数据，数据不足时明确说明缺失项。",
        "data_label": "演示数据",
    }


@router.get("/messages")
def list_messages(db: DbSession, auth: CurrentAuth,
                  agent_key: str | None = None, permission_level: str | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """AI 消息审计视图：每条回答的意图、权限级别、数据充分性可回溯。"""
    auth.require("ai", "VIEW")
    conv_ids = list(db.scalars(select(AIConversation.id).where(
        AIConversation.user_id == auth.user.id)).all())
    if not conv_ids:
        return paginate([], page, page_size)
    q = select(AIMessage).where(AIMessage.conversation_id.in_(conv_ids),
                                AIMessage.role == "assistant")
    if agent_key:
        q = q.where(AIMessage.agent_key == agent_key)
    if permission_level:
        q = q.where(AIMessage.permission_level == permission_level)
    rows = list(db.scalars(q.order_by(AIMessage.id.desc())).all())
    items = [{
        "id": m.id, "conversation_id": m.conversation_id,
        "agent_key": m.agent_key, "agent_name": m.agent_name,
        "intent": m.intent, "content": (m.content or "")[:200],
        "permission_level": m.permission_level, "decision_status": m.decision_status,
        "data_sufficient": m.data_sufficient,
        "evidence": m.evidence, "tokens": m.tokens, "latency_ms": m.latency_ms,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    } for m in rows]
    return paginate(items, page, page_size)
