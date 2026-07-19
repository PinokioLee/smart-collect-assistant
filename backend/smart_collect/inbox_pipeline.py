"""이벤트 1건을 자율 처리하는 Inbox Intake 파이프라인.

Gmail/Mock → 계층형 분류 → 취합 요청 분석 → 양식 선택/생성 → 작성 가이드와
메일 생성 → LLM+정책 자율성 판단 → 자동 발송 또는 승인 큐 저장.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import ensure_dirs
from .store import init_db, is_processed, list_records, upsert_record
from .tools import directory_tools, guide_tools
from .tools.email_tools import EmailSendRequest, send_email
from .tools.inbox_tools import InboxAdapter, InboxMessage, get_inbox_adapter
from .tools.mail_classifier import ClassificationResult, classify_message
from .tools.mail_decision import AutonomyDecision, choose_template_action, decide_autonomy
from .tools.requirement_tools import analyze_collection_email
from .tools.requirement_tools import build_validation_rules
from .tools.template_tools import build_and_save_template, design_template_from_intent


def _matching_attachment_paths(msg: InboxMessage, filename: str) -> list[str]:
    return [p for p in msg.attachment_paths if Path(p).name == Path(filename).name]


def _prepare_template(msg: InboxMessage, req, *, prefer_llm: bool) -> dict:
    """기존 엑셀 양식을 선택하거나 요구사항으로 새 양식을 생성한다."""
    excel_names = [
        name for name in msg.attachments
        if name.lower().endswith((".xlsx", ".xls"))
    ]
    strategy = choose_template_action(msg, req, prefer_llm=prefer_llm)
    if strategy == "use_attached" and excel_names:
        name = excel_names[0]
        return {
            "strategy": "use_attached",
            "template_id": None,
            "filename": name,
            "attachment_paths": _matching_attachment_paths(msg, name),
            "download": None,
            "validation_rule": build_validation_rules(req).model_dump(),
        }

    if strategy == "review":
        return {
            "strategy": "review",
            "template_id": None,
            "filename": excel_names[0] if excel_names else "양식 확인 필요",
            "attachment_paths": [],
            "download": None,
            "validation_rule": {},
        }

    intent = "\n".join([
        f"제목: {req.request_title or msg.subject}",
        f"목적: {req.purpose or msg.body[:500]}",
        f"작성 항목: {', '.join(req.required_fields)}",
        f"제출 기한: {req.deadline or ''}",
        f"주의사항: {', '.join(req.cautions)}",
    ])
    spec = design_template_from_intent(intent, prefer_llm=prefer_llm)
    if req.deadline and not spec.deadline:
        spec.deadline = req.deadline
    built = build_and_save_template(spec)
    return {
        "strategy": "generate",
        "template_id": built["template_id"],
        "filename": built["filename"],
        "attachment_paths": [built["excel_path"]],
        "download": built["download"],
        "template_source": spec.source,
        "validation_rule": built["validation_rule"],
    }


def _build_collection_request(
    msg: InboxMessage,
    classification: ClassificationResult,
    *,
    prefer_llm: bool,
    auto_send_enabled: bool | None,
) -> tuple[dict, list[dict], dict, dict, AutonomyDecision]:
    req = analyze_collection_email(msg.subject, msg.body, prefer_llm=prefer_llm)
    recipients, recipient_source = directory_tools.resolve_collection_recipients(msg)
    artifact = _prepare_template(msg, req, prefer_llm=prefer_llm)
    artifact["recipient_source"] = recipient_source

    from .tools.advanced_rag import build_rag_context

    rag = build_rag_context(req, recipients, subject=msg.subject, prefer_llm=prefer_llm)
    style_samples = None
    try:
        from .tools.rag_tools import retrieve_style_samples

        style_samples = retrieve_style_samples(" ".join(req.required_fields), top_k=2)
    except Exception:
        pass

    guide = guide_tools.generate_writing_guide(
        req,
        references=rag.get("retrieved") or None,
        prefer_llm=prefer_llm,
    )
    draft = guide_tools.create_request_mail(
        guide.get("guide_body", ""),
        recipients,
        req.deadline,
        artifact["filename"],
        style_samples=style_samples,
        prefer_llm=prefer_llm,
    )
    from .tools.advanced_rag import verify_generated_draft
    post_grounding = verify_generated_draft(
        draft.get("mail_body", ""), req, artifact["filename"], rag.get("retrieved", []),
    )
    rag["grounding"] = {
        "checks": post_grounding["checks"],
        "flags": post_grounding["flags"],
        "score": post_grounding["score"],
    }
    rag["claim_sources"] = post_grounding["claim_sources"]
    decision = decide_autonomy(
        msg,
        req,
        classification,
        recipients,
        rag.get("grounding", {}),
        artifact.get("attachment_paths", []),
        auto_send_enabled=auto_send_enabled,
        prefer_llm=prefer_llm,
        template_action_override=artifact.get("strategy"),
    )
    artifact["requirements"] = req.model_dump()
    artifact["guide"] = guide
    artifact["claim_sources"] = rag.get("claim_sources", {})
    return draft, recipients, rag, artifact, decision


def _record_from(
    msg: InboxMessage,
    cls: ClassificationResult,
    *,
    status: str,
    draft: dict | None = None,
    recipients: list[dict] | None = None,
    rag: dict | None = None,
    artifacts: dict | None = None,
    decision: AutonomyDecision | None = None,
    error: str | None = None,
) -> dict:
    rag = rag or {}
    return {
        "message_id": msg.id,
        "sender": msg.sender,
        "subject": msg.subject,
        "received_at": msg.received_at,
        "classification": cls.label,
        "intent": cls.intent,
        "confidence": cls.confidence,
        "tier": cls.tier,
        "status": status,
        "draft_subject": (draft or {}).get("mail_subject"),
        "draft_body": (draft or {}).get("mail_body"),
        "recipients": recipients or [],
        "reasons": cls.reasons,
        "risk_flags": list(dict.fromkeys(cls.risk_flags + ((decision or AutonomyDecision()).risk_flags))),
        "decision": decision.to_dict() if decision else {},
        "artifacts": artifacts or {},
        "source": cls.source,
        "sent": status == "sent",
        "sent_message_id": None,
        "error": error,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "grounding": rag.get("grounding", {}),
        "sources": rag.get("sources", []),
    }


def _send_record(record: dict) -> dict:
    to = [r.get("email", "") for r in record.get("recipients", []) if r.get("email")]
    paths = [
        p for p in record.get("artifacts", {}).get("attachment_paths", [])
        if Path(p).exists()
    ]
    reply = record.get("artifacts", {}).get("reply_context", {})
    result = send_email(EmailSendRequest(
        to=to,
        subject=record.get("draft_subject") or "[취합 요청]",
        body=record.get("draft_body") or "",
        attachment_paths=paths,
        thread_id=str(reply.get("thread_id") or ""),
        in_reply_to=str(reply.get("in_reply_to") or ""),
        references=str(reply.get("references") or ""),
    ))
    record["status"] = "sent"
    record["sent"] = True
    record["sent_message_id"] = result.get("message_id")
    record["artifacts"]["send_result"] = result
    return record


def ingest_inbox(
    *,
    adapter: InboxAdapter | None = None,
    db_path=None,
    prefer_llm: bool = True,
    max_results: int = 100,
    auto_send_enabled: bool | None = None,
) -> dict:
    ensure_dirs()
    init_db(db_path)
    adapter = adapter or get_inbox_adapter()
    messages = adapter.list_new(max_results)
    processed_new = 0
    skipped = 0
    from .autonomous_graph import run_mail_event

    for msg in messages:
        if is_processed(msg.id, db_path):
            skipped += 1
            continue
        record = run_mail_event(
            msg, db_path=db_path, prefer_llm=prefer_llm,
            auto_send_enabled=auto_send_enabled,
        )
        upsert_record(record, db_path)
        processed_new += 1

    queue = list_records(db_path=db_path)
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_intent: dict[str, int] = {}
    for record in queue:
        by_status[record["status"]] = by_status.get(record["status"], 0) + 1
        category = record.get("classification") or "미분류"
        by_category[category] = by_category.get(category, 0) + 1
        intent = record.get("intent") or "other"
        by_intent[intent] = by_intent.get(intent, 0) + 1
    return {
        "fetched": len(messages),
        "processed_new": processed_new,
        "skipped": skipped,
        "by_status": by_status,
        "by_category": by_category,
        "by_intent": by_intent,
        "automation": {
            "sent": by_status.get("sent", 0),
            "review_required": by_status.get("draft_ready", 0) + by_status.get("needs_review", 0),
            "quarantined": by_status.get("quarantined", 0),
        },
        "queue": queue,
    }
