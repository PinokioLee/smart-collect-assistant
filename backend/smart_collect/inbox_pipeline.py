"""수신함 파이프라인 (Phase A) — 읽기 → 분류 → 초안 생성 → 검토 큐.

흐름
----
1. 수신함 수집(InboxAdapter: mock 또는 gmail.readonly)
2. 이미 처리한 메일은 건너뜀(중복 방지, store)
3. 메일 분류(일반 / 취합요청, 확신도 3단계)
4. 취합 요청(auto)로 판단되면:
   - 요구사항 추출(requirement_tools)
   - 작성 가이드 + 담당자별 요청 메일 '초안' 생성(guide_tools)
   - 수신자는 조직도(directory_tools)에서 가져옴 — RAG 로 추측하지 않음
5. 처리 결과를 검토 큐(store)에 저장 → 사람이 승인 후 발송(기존 발송 경로)

자동 발송은 하지 않는다(Human-in-the-loop).
"""

from __future__ import annotations

from datetime import datetime

from .config import ensure_dirs
from .store import init_db, is_processed, list_records, upsert_record
from .tools import directory_tools, guide_tools
from .tools.inbox_tools import InboxAdapter, InboxMessage, get_inbox_adapter
from .tools.mail_classifier import ClassificationResult, classify_message
from .tools.requirement_tools import analyze_collection_email


def _build_draft_for_collection(
    msg: InboxMessage, *, prefer_llm: bool
) -> tuple[dict, list[dict], dict]:
    """취합 요청 메일 → 요청 메일 초안 + 수신자 + 고급 RAG 컨텍스트(근거 검증)."""
    req = analyze_collection_email(msg.subject, msg.body, prefer_llm=prefer_llm)
    recipients = directory_tools.lookup_recipients()  # 조직도 기반(추측 금지)

    # 고급 RAG: 쿼리 재작성 → 메타데이터 필터 검색 → 근거 검증
    from .tools.advanced_rag import build_rag_context

    rag = build_rag_context(
        req, recipients, subject=msg.subject, prefer_llm=prefer_llm
    )

    style_samples = None
    try:
        from .tools.rag_tools import retrieve_style_samples

        style_samples = retrieve_style_samples(" ".join(req.required_fields), top_k=2)
    except Exception:  # noqa: BLE001 - 스타일 없어도 진행
        style_samples = None

    guide = guide_tools.generate_writing_guide(req)
    attachment = msg.attachments[0] if msg.attachments else "취합_양식.xlsx"
    draft = guide_tools.create_request_mail(
        guide.get("guide_body", ""),
        recipients,
        req.deadline,
        attachment,
        style_samples=style_samples,
    )
    return draft, recipients, rag


def _record_from(
    msg: InboxMessage, cls: ClassificationResult,
    draft: dict | None, recipients: list[dict] | None,
    status: str, error: str | None = None, rag: dict | None = None,
) -> dict:
    rag = rag or {}
    return {
        "message_id": msg.id,
        "sender": msg.sender,
        "subject": msg.subject,
        "received_at": msg.received_at,
        "classification": cls.label,
        "confidence": cls.confidence,
        "tier": cls.tier,
        "status": status,
        "draft_subject": (draft or {}).get("mail_subject"),
        "draft_body": (draft or {}).get("mail_body"),
        "recipients": recipients or [],
        "reasons": cls.reasons,
        "source": cls.source,
        "sent": 0,
        "error": error,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "grounding": rag.get("grounding", {}),
        "sources": rag.get("sources", []),
    }


def ingest_inbox(
    *,
    adapter: InboxAdapter | None = None,
    db_path=None,
    prefer_llm: bool = True,
    max_results: int = 20,
) -> dict:
    """수신함 1회 수집·분류·초안 생성 후 결과 요약을 반환한다.

    Returns: {fetched, processed_new, skipped, by_status, queue}
    """
    ensure_dirs()
    init_db(db_path)
    adapter = adapter or get_inbox_adapter()

    messages = adapter.list_new(max_results)
    processed_new = 0
    skipped = 0

    for msg in messages:
        if is_processed(msg.id, db_path):
            skipped += 1
            continue

        cls = classify_message(msg, prefer_llm=prefer_llm)

        if cls.tier == "auto":
            try:
                draft, recipients, rag = _build_draft_for_collection(
                    msg, prefer_llm=prefer_llm
                )
                record = _record_from(
                    msg, cls, draft, recipients, status="draft_ready", rag=rag
                )
            except Exception as exc:  # noqa: BLE001 - 초안 실패해도 큐에는 남김
                record = _record_from(
                    msg, cls, None, None, status="error", error=str(exc)
                )
        elif cls.tier == "review":
            record = _record_from(msg, cls, None, None, status="needs_review")
        else:
            record = _record_from(msg, cls, None, None, status="general")

        upsert_record(record, db_path)
        processed_new += 1

    queue = list_records(db_path=db_path)
    by_status: dict[str, int] = {}
    for r in queue:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    return {
        "fetched": len(messages),
        "processed_new": processed_new,
        "skipped": skipped,
        "by_status": by_status,
        "queue": queue,
    }
