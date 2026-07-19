"""이벤트 기반 자율형 Inbox Multi-Agent LangGraph.

Supervisor가 메일 상태를 보고 허용된 Worker 중 다음 행동을 선택한다. Worker 결과를
Observation으로 다시 받아 실패 시 재계획하고, 두 번째 실패는 사람 확인으로 종료한다.
각 판단/도구 호출은 job_store.agent_actions에 기록된다.
"""

from __future__ import annotations

import re
from email.utils import parseaddr
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import job_store
from .config import DATA_DIR, settings
from .state import ValidationRule
from .tools.email_tools import EmailSendRequest, send_email
from .tools.excel_tools import load_excel_files, merge_valid_rows, validate_excel_data
from .tools.inbox_tools import InboxMessage
from .tools.mail_classifier import ClassificationResult, classify_message


class InboxAgentState(TypedDict, total=False):
    event_id: str
    message: InboxMessage
    db_path: str | None
    prefer_llm: bool
    auto_send_enabled: bool | None
    classification: ClassificationResult
    route: str
    attempt: int
    outcome: str
    observation: dict
    record: dict
    job_id: str | None
    terminal: bool


def _db(state: InboxAgentState):
    return state.get("db_path")


def _log(state: InboxAgentState, agent: str, action: str, outcome: str, detail=None) -> None:
    job_store.log_action(
        state["event_id"], agent, action, outcome, detail or {},
        job_id=state.get("job_id"), db_path=_db(state),
    )


def _intake(state: InboxAgentState) -> dict:
    cls = classify_message(state["message"], prefer_llm=state.get("prefer_llm", True))
    _log(state, "Inbox Intake Agent", "classify_mail", "success", cls.to_dict())
    return {"classification": cls, "attempt": 0, "outcome": "classified"}


def _allowed_routes(cls: ClassificationResult) -> list[str]:
    if cls.category == "spam":
        return ["quarantine"]
    if cls.category == "general":
        return ["general"]
    # Supervisor가 분류 결과를 그대로 실행하는 단순 switch가 되지 않도록 모든 업무
    # capability를 후보로 제공한다. 최종 실행 전에는 _policy_route가 side-effect가 있는
    # Worker와 의도의 호환성을 다시 검증한다.
    return [
        "request_worker", "submission_worker", "qa_worker",
        "extension_worker", "human_review",
    ]


def _default_route(cls: ClassificationResult) -> str:
    if cls.category == "spam":
        return "quarantine"
    if cls.category == "general":
        return "general"
    return {
        "request": "request_worker",
        "submission": "submission_worker",
        "correction": "submission_worker",
        "question": "qa_worker",
        "extension": "extension_worker",
    }.get(cls.intent, "human_review")


def _policy_route(cls: ClassificationResult, proposed: str | None) -> tuple[str | None, str | None]:
    """LLM route가 메일을 변경하는 Worker의 최소 안전 계약을 지키는지 검증한다."""
    if proposed in {"general", "quarantine", "human_review", None}:
        return proposed, None
    compatible = {
        "request_worker": {"request"},
        "submission_worker": {"submission", "correction"},
        "qa_worker": {"question"},
        "extension_worker": {"extension"},
    }
    if cls.intent in compatible.get(proposed, set()):
        return proposed, None
    return "human_review", f"route_intent_mismatch:{proposed}/{cls.intent}"


def _llm_route(state: InboxAgentState, allowed: list[str]) -> tuple[str | None, str]:
    if not state.get("prefer_llm", True) or not settings.azure_ready:
        return None, "LLM unavailable/disabled"
    try:
        from .llm import chat_json

        cls = state["classification"]
        msg = state["message"]
        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": allowed},
                "reason": {"type": "string"},
            },
            "required": ["action", "reason"],
            "additionalProperties": False,
        }
        data = chat_json([{"role": "user", "content": f"""당신은 Inbox Supervisor Agent입니다.
현재 상태와 허용된 행동을 보고 다음 행동 하나를 선택하세요. 실패 관찰이 있으면 다른 안전한
행동으로 재계획하세요. JSON만 응답: {{"action":"허용 행동","reason":"근거"}}
허용 행동: {allowed}
Worker capability:
- request_worker: 신규 취합 요청 분석·양식 결정·요청 메일 준비
- submission_worker: 제출/수정본 Excel 검증·반려 또는 병합
- qa_worker: 기존 Collection Job의 작성 질문에 근거 기반 답변
- extension_worker: 마감 연장 요청을 승인 대기로 전달
- human_review: 의도가 불명확하거나 정책·데이터가 부족할 때 사람에게 전달
분류: {cls.category}/{cls.intent}, 신뢰도={cls.confidence}
이전 결과: {state.get('outcome')}, 관찰: {state.get('observation', {})}
제목: {msg.subject}, 첨부: {msg.attachments}
본문: {msg.body[:1800]}"""}], schema_name="supervisor_route", schema=schema, temperature=0.0)
        if not isinstance(data, dict):
            return None, "empty LLM response"
        action = str(data.get("action") or "")
        return (action if action in allowed else None), str(data.get("reason") or "")
    except Exception as exc:
        return None, f"LLM route failed: {exc}"


def _supervisor(state: InboxAgentState) -> dict:
    cls = state["classification"]
    if state.get("attempt", 0) > 0 and state.get("outcome") == "failure":
        observation = state.get("observation", {})
        retryable = _is_retryable_failure(observation)
        if retryable and state.get("attempt", 0) < 2:
            allowed = _allowed_routes(cls)
            proposed, llm_reason = _llm_route(state, allowed)
            safe_proposed, override = _policy_route(cls, proposed)
            route = safe_proposed or _default_route(cls)
            reason = llm_reason or "일시적 Worker 오류로 동일 업무를 1회 재시도"
            if override:
                reason = f"{reason}; Policy Gate={override}"
            source = "llm" if proposed else "retry-policy"
        else:
            route = "human_review"
            reason = "복구 불가능한 실패 또는 재시도 한도 도달로 사람 확인에 재계획"
            source = "policy"
    else:
        allowed = _allowed_routes(cls)
        proposed, reason = _llm_route(state, allowed)
        safe_proposed, override = _policy_route(cls, proposed)
        route = safe_proposed or _default_route(cls)
        if override:
            reason = f"{reason}; Policy Gate={override}"
        source = "llm" if proposed else "policy"
    _log(state, "Supervisor Agent", "select_next_action", "success", {
        "route": route, "reason": reason, "source": source,
    })
    return {"route": route}


def _is_retryable_failure(observation: dict | None) -> bool:
    """상태 변화 없이 재실행해도 의미가 있는 일시 오류만 제한적으로 재시도한다."""
    observation = observation or {}
    reason = str(observation.get("reason") or "").lower()
    error = str(observation.get("error") or "").lower()
    if reason in {"job_not_found", "attachment_unavailable"}:
        return False
    transient_tokens = (
        "timeout", "timed out", "temporary", "temporarily", "rate limit",
        "429", "connection reset", "connection aborted", "service unavailable", "503",
    )
    return any(token in error for token in transient_tokens)


def _route(state: InboxAgentState) -> str:
    return state["route"]


def _base_record(state: InboxAgentState, status: str, **extra) -> dict:
    from .inbox_pipeline import _record_from

    return _record_from(state["message"], state["classification"], status=status, **extra)


def _general(state: InboxAgentState) -> dict:
    record = _base_record(state, "general")
    _log(state, "General Mail Agent", "archive_without_action", "success")
    return {"record": record, "outcome": "success", "terminal": True}


def _quarantine(state: InboxAgentState) -> dict:
    record = _base_record(state, "quarantined")
    _log(state, "Security Agent", "quarantine_mail", "success", {
        "risk_flags": state["classification"].risk_flags,
    })
    return {"record": record, "outcome": "success", "terminal": True}


def _job_id(message_id: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_-]", "", message_id)[-18:] or "REQUEST"
    return f"SC-{safe}"


def _request_worker(state: InboxAgentState) -> dict:
    from .inbox_pipeline import _build_collection_request, _record_from, _send_record

    msg, cls = state["message"], state["classification"]
    try:
        draft, recipients, rag, artifacts, decision = _build_collection_request(
            msg, cls,
            prefer_llm=state.get("prefer_llm", True),
            auto_send_enabled=state.get("auto_send_enabled"),
        )
        jid = _job_id(msg.id)
        if not str(draft.get("mail_subject") or "").startswith(f"[{jid}]"):
            draft["mail_subject"] = f"[{jid}] {draft.get('mail_subject') or '[취합 요청]'}"
        draft["mail_body"] = f"취합 작업번호: {jid}\n\n{draft.get('mail_body') or ''}"
        artifacts["job_id"] = jid
        paths = artifacts.get("attachment_paths", [])
        job_store.create_job({
            "job_id": jid,
            "source_message_id": msg.id,
            "source_thread_id": msg.thread_id,
            "title": artifacts.get("requirements", {}).get("request_title") or msg.subject,
            "deadline": artifacts.get("requirements", {}).get("deadline"),
            "recipients": recipients,
            "required_fields": artifacts.get("requirements", {}).get("required_fields", []),
            "validation_rule": artifacts.get("validation_rule", {}),
            "template_id": artifacts.get("template_id"),
            "template_path": paths[0] if paths else None,
            "status": "collecting" if decision.action == "auto_send" else "awaiting_approval",
        }, _db(state))
        record = _record_from(
            msg, cls, status="draft_ready", draft=draft, recipients=recipients,
            rag=rag, artifacts=artifacts, decision=decision,
        )
        if decision.action == "auto_send":
            record = _send_record(record)
        _log(state, "Template/Communication Agent", "prepare_collection_request", "success", {
            "job_id": jid, "template_strategy": artifacts.get("strategy"),
            "send_action": decision.action,
        })
        return {"record": record, "job_id": jid, "outcome": "success", "terminal": True}
    except Exception as exc:
        _log(state, "Template/Communication Agent", "prepare_collection_request", "failure", {"error": str(exc)})
        return {"outcome": "failure", "observation": {"error": str(exc)}, "terminal": False}


def _sender_email(msg: InboxMessage) -> str:
    return parseaddr(msg.sender)[1].strip().lower()


def _auto_response_allowed(email: str, state: InboxAgentState) -> bool:
    enabled = settings.auto_send_enabled if state.get("auto_send_enabled") is None else state.get("auto_send_enabled")
    if not enabled or "@" not in email or not settings.auto_send_allowed_domains:
        return False
    return email.rsplit("@", 1)[-1] in settings.auto_send_allowed_domains


def _rejection_draft(job: dict, errors: list[dict], *, prefer_llm: bool) -> dict:
    summary = "\n".join(
        f"- {e.get('column') or '양식'} {e.get('row')}행: {e.get('error_type')} ({e.get('detail') or ''})"
        for e in errors[:12]
    )
    if prefer_llm and settings.azure_ready:
        try:
            from .llm import chat_json
            data = chat_json([{"role": "user", "content": f"""검증 실패 사유를 제출자가 바로 수정할 수 있는
정중한 반려 메일로 작성하세요. 오류 사실은 바꾸거나 추가하지 마세요.
JSON만 응답: {{"subject":"제목","body":"본문"}}
작업번호: {job['job_id']}, 오류:\n{summary}"""}], schema_name="rejection_mail", schema={
                "type": "object",
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"],
                "additionalProperties": False,
            }, temperature=0.2)
            if data and data.get("body"):
                return {"mail_subject": data.get("subject") or "자료 수정 요청", "mail_body": data["body"]}
        except Exception:
            pass
    return {
        "mail_subject": f"[{job['job_id']}] 제출 자료 수정 요청",
        "mail_body": f"안녕하세요. 제출하신 자료에서 아래 오류를 확인했습니다.\n\n{summary}\n\n수정 후 동일 작업번호로 다시 제출해 주세요.",
    }


def _llm_rejection_is_simple(errors: list[dict], *, prefer_llm: bool) -> tuple[bool, str]:
    """반려 메일을 자동 발송해도 되는 단순 검증 오류인지 LLM이 제안한다."""
    if not prefer_llm or not settings.azure_ready:
        return False, "LLM 판단 없음"
    try:
        from .llm import chat_json
        facts = [{"type": e.get("error_type"), "column": e.get("column"), "row": e.get("row")} for e in errors[:20]]
        data = chat_json([{"role": "user", "content": f"""다음은 코드 검증으로 확정된 Excel 오류입니다.
오류 사실만 안내하는 반복적 반려인지, 담당자 판단이 필요한 복잡한 예외인지 평가하세요.
JSON만 응답: {{"simple":true|false,"requires_review":true|false,"reason":"근거"}}
오류: {facts}"""}], schema_name="rejection_autonomy", schema={
            "type": "object",
            "properties": {
                "simple": {"type": "boolean"},
                "requires_review": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["simple", "requires_review", "reason"],
            "additionalProperties": False,
        }, temperature=0.0)
        if not data:
            return False, "빈 LLM 판단"
        simple = bool(data.get("simple")) and not bool(data.get("requires_review"))
        return simple, str(data.get("reason") or "")
    except Exception as exc:
        return False, f"LLM 판단 실패: {exc}"


def _submission_worker(state: InboxAgentState) -> dict:
    msg, cls = state["message"], state["classification"]
    job = job_store.find_job_for_message(f"{msg.subject}\n{msg.body}", msg.thread_id, _db(state))
    if not job:
        _log(state, "Validation Agent", "match_collection_job", "failure", {"reason": "job_not_found"})
        return {"outcome": "failure", "observation": {"reason": "job_not_found"}, "terminal": False}
    paths = [p for p in msg.attachment_paths if Path(p).suffix.lower() in {".xlsx", ".xls"} and Path(p).exists()]
    if not paths:
        _log(state, "Validation Agent", "load_submission", "failure", {"reason": "attachment_unavailable"})
        return {"job_id": job["job_id"], "outcome": "failure", "observation": {"reason": "attachment_unavailable"}, "terminal": False}
    try:
        rule = ValidationRule.model_validate(job.get("validation_rule") or {})
        loaded = load_excel_files(paths)
        result = validate_excel_data(loaded, rule)
        errors = [e.model_dump() for e in result.error_details]
    except Exception as exc:
        _log(state, "Validation Agent", "validate_submission", "failure", {"error": str(exc)})
        return {"job_id": job["job_id"], "outcome": "failure", "observation": {"error": str(exc)}, "terminal": False}

    email = _sender_email(msg)
    if errors:
        job_store.add_submission({
            "job_id": job["job_id"], "message_id": msg.id, "sender": email,
            "attachment_paths": paths, "status": "rejected", "errors": errors,
            "submitted_at": msg.received_at,
        }, _db(state))
        draft = _rejection_draft(job, errors, prefer_llm=state.get("prefer_llm", True))
        recipients = [{"name": email, "dept": "", "email": email}] if email else []
        llm_simple, llm_reason = _llm_rejection_is_simple(
            errors, prefer_llm=state.get("prefer_llm", True)
        )
        auto = bool(email and llm_simple and _auto_response_allowed(email, state))
        decision = {
            "action": "auto_send" if auto else "review",
            "source": "llm+validation-policy", "complexity": "simple",
            "reasons": [f"결정론 검증 오류 {len(errors)}건", llm_reason],
            "risk_flags": [] if llm_simple else ["llm_requested_review"],
        }
        record = _base_record(
            state, "draft_ready", draft=draft, recipients=recipients,
            artifacts={"job_id": job["job_id"], "validation_errors": errors},
        )
        record["decision"] = decision
        if auto:
            from .inbox_pipeline import _send_record
            record = _send_record(record)
        _log(state, "Validation/Communication Agent", "reject_and_request_resubmission", "success", {
            "error_count": len(errors), "auto_sent": auto,
        })
        return {"record": record, "job_id": job["job_id"], "outcome": "success", "terminal": True}

    job_store.add_submission({
        "job_id": job["job_id"], "message_id": msg.id, "sender": email,
        "attachment_paths": paths, "status": "accepted", "errors": [],
        "submitted_at": msg.received_at,
    }, _db(state))
    accepted = [s for s in job_store.list_submissions(job["job_id"], _db(state)) if s["status"] == "accepted"]
    recipient_count = len(job.get("recipients") or [])
    complete = recipient_count > 0 and len({s["sender"] for s in accepted}) >= recipient_count
    artifacts: dict[str, Any] = {"job_id": job["job_id"], "validation": result.model_dump()}
    if complete:
        all_paths = [p for s in accepted for p in s["attachment_paths"]]
        loaded_all = load_excel_files(all_paths)
        final_validation = validate_excel_data(loaded_all, rule)
        out = DATA_DIR / "merged_files" / f"{job['job_id']}_merged.xlsx"
        merged_path, rows = merge_valid_rows(loaded_all, final_validation, out)
        artifacts.update({"merged_file": merged_path, "merged_rows": rows})
        job_store.update_job(job["job_id"], status="completed", result=artifacts, db_path=_db(state))
    else:
        job_store.update_job(job["job_id"], status="partial", result={"accepted": len(accepted)}, db_path=_db(state))
    record = _base_record(state, "submission_accepted", artifacts=artifacts)
    _log(state, "Validation/Merge Agent", "accept_submission", "success", {
        "job_id": job["job_id"], "complete": complete, "accepted": len(accepted),
    })
    return {"record": record, "job_id": job["job_id"], "outcome": "success", "terminal": True}


def _qa_worker(state: InboxAgentState) -> dict:
    msg = state["message"]
    job = job_store.find_job_for_message(f"{msg.subject}\n{msg.body}", msg.thread_id, _db(state))
    if not job:
        _log(state, "Q&A RAG Agent", "find_grounding_context", "failure", {"reason": "job_not_found"})
        return {"outcome": "failure", "observation": {"reason": "job_not_found"}, "terminal": False}
    facts = {
        "작업번호": job["job_id"], "제목": job.get("title"), "마감": job.get("deadline"),
        "작성항목": job.get("required_fields"), "양식": Path(job.get("template_path") or "").name,
    }
    answer = None
    if state.get("prefer_llm", True) and settings.azure_ready:
        try:
            from .llm import chat_json
            answer = chat_json([{"role": "user", "content": f"""취합 담당자의 질문에 아래 확인된 사실만 사용해 답하세요.
근거에 없는 정책·연장은 추측하지 말고 담당자 확인이 필요하다고 쓰세요.
JSON만 응답: {{"subject":"제목","body":"본문","grounded":true|false}}
확인 사실: {facts}\n질문: {msg.body[:1600]}"""}], schema_name="grounded_answer", schema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "grounded": {"type": "boolean"},
                },
                "required": ["subject", "body", "grounded"],
                "additionalProperties": False,
            }, temperature=0.1)
        except Exception:
            answer = None
    data = answer if isinstance(answer, dict) else None
    draft = {
        "mail_subject": (data or {}).get("subject") or f"[{job['job_id']}] 문의 답변",
        "mail_body": (data or {}).get("body") or f"확인된 제출 기한은 {job.get('deadline') or '담당자 확인 필요'}이며, 작성 항목은 {', '.join(job.get('required_fields') or [])}입니다.",
    }
    email = _sender_email(msg)
    grounded = bool((data or {}).get("grounded", False))
    auto = bool(grounded and email and _auto_response_allowed(email, state))
    recipients = [{"name": email, "dept": "", "email": email}] if email else []
    record = _base_record(
        state, "draft_ready", draft=draft, recipients=recipients,
        artifacts={"job_id": job["job_id"], "answer_facts": facts},
    )
    record["decision"] = {
        "action": "auto_send" if auto else "review", "source": "llm+grounding-policy",
        "reasons": ["답변 근거 확인" if grounded else "근거 불충분"],
        "risk_flags": [] if grounded else ["ungrounded_answer"],
    }
    if auto:
        from .inbox_pipeline import _send_record
        record = _send_record(record)
    _log(state, "Q&A RAG/Communication Agent", "answer_question", "success", {
        "grounded": grounded, "auto_sent": auto,
    })
    return {"record": record, "job_id": job["job_id"], "outcome": "success", "terminal": True}


def _extension_worker(state: InboxAgentState) -> dict:
    msg = state["message"]
    job = job_store.find_job_for_message(f"{msg.subject}\n{msg.body}", msg.thread_id, _db(state))
    decision = {
        "action": "review", "source": "policy", "complexity": "complex",
        "reasons": ["마감 연장은 업무 정책 변경이므로 담당자 승인 필요"],
        "risk_flags": ["policy_exception"],
    }
    record = _base_record(
        state, "needs_review", artifacts={"job_id": (job or {}).get("job_id")},
    )
    record["decision"] = decision
    _log(state, "Deadline Agent", "request_deadline_approval", "success", decision)
    return {"record": record, "job_id": (job or {}).get("job_id"), "outcome": "success", "terminal": True}


def _human_review(state: InboxAgentState) -> dict:
    record = state.get("record") or _base_record(state, "needs_review")
    record["status"] = "needs_review"
    record["decision"] = {
        "action": "review", "source": "supervisor-replan",
        "reasons": [f"자동 Worker 처리 실패/불확실: {state.get('observation', {})}"],
        "risk_flags": ["manual_intervention_required"],
    }
    _log(state, "Supervisor Agent", "handoff_to_human", "success", state.get("observation", {}))
    return {"record": record, "outcome": "review", "terminal": True}


def _observe(state: InboxAgentState) -> dict:
    if state.get("outcome") == "failure" and state.get("attempt", 0) < 2:
        _log(state, "Supervisor Agent", "observe_worker_result", "retry", state.get("observation", {}))
        return {"attempt": state.get("attempt", 0) + 1, "terminal": False}
    _log(state, "Supervisor Agent", "observe_worker_result", "complete", {"outcome": state.get("outcome")})
    return {"terminal": True}


def _after_observe(state: InboxAgentState) -> str:
    return "retry" if not state.get("terminal", True) else "end"


def build_inbox_agent_graph():
    graph = StateGraph(InboxAgentState)
    graph.add_node("intake", _intake)
    graph.add_node("supervisor", _supervisor)
    graph.add_node("general", _general)
    graph.add_node("quarantine", _quarantine)
    graph.add_node("request_worker", _request_worker)
    graph.add_node("submission_worker", _submission_worker)
    graph.add_node("qa_worker", _qa_worker)
    graph.add_node("extension_worker", _extension_worker)
    graph.add_node("human_review", _human_review)
    graph.add_node("observe", _observe)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "supervisor")
    graph.add_conditional_edges("supervisor", _route, {
        "general": "general", "quarantine": "quarantine",
        "request_worker": "request_worker", "submission_worker": "submission_worker",
        "qa_worker": "qa_worker", "extension_worker": "extension_worker",
        "human_review": "human_review",
    })
    for node in ("request_worker", "submission_worker", "qa_worker", "extension_worker"):
        graph.add_edge(node, "observe")
    graph.add_conditional_edges("observe", _after_observe, {"retry": "supervisor", "end": END})
    for node in ("general", "quarantine", "human_review"):
        graph.add_edge(node, END)
    return graph.compile()


def run_mail_event(
    message: InboxMessage, *, db_path=None, prefer_llm: bool = True,
    auto_send_enabled: bool | None = None,
) -> dict:
    job_store.init_job_tables(db_path)
    initial: InboxAgentState = {
        "event_id": message.id, "message": message,
        "db_path": str(db_path) if db_path else None,
        "prefer_llm": prefer_llm, "auto_send_enabled": auto_send_enabled,
    }
    result = build_inbox_agent_graph().invoke(initial)
    record = result.get("record") or _base_record(result, "needs_review")
    record.setdefault("artifacts", {})["agent_trace"] = job_store.list_actions(message.id, db_path)
    record["artifacts"]["architecture"] = "agentic_supervisor_graph"
    return record


def run_fixed_mail_event(
    message: InboxMessage, *, db_path=None, prefer_llm: bool = True,
    auto_send_enabled: bool | None = None,
) -> dict:
    """비교 실험용 고정 Workflow.

    동일한 Intake와 Worker Tool을 사용하지만 Worker 결과를 관찰해 재계획하지 않는다.
    따라서 Agentic Graph와의 비교가 임의 행동표가 아니라 실제 코드 경로의 차이를
    측정하게 된다. 운영 진입점은 ``run_mail_event``이다.
    """
    job_store.init_job_tables(db_path)
    state: InboxAgentState = {
        "event_id": message.id,
        "message": message,
        "db_path": str(db_path) if db_path else None,
        "prefer_llm": prefer_llm,
        "auto_send_enabled": auto_send_enabled,
    }
    state.update(_intake(state))
    route = _default_route(state["classification"])
    state["route"] = route
    _log(state, "Fixed Workflow", "select_fixed_action", "success", {"route": route})
    handlers = {
        "general": _general,
        "quarantine": _quarantine,
        "request_worker": _request_worker,
        "submission_worker": _submission_worker,
        "qa_worker": _qa_worker,
        "extension_worker": _extension_worker,
        "human_review": _human_review,
    }
    result = handlers[route](state)
    state.update(result)
    if result.get("outcome") == "failure":
        _log(state, "Fixed Workflow", "stop_on_worker_failure", "failure", result.get("observation", {}))
        record = _base_record(
            state,
            "processing_error",
            error=str(result.get("observation") or "worker_failure"),
        )
    else:
        record = result.get("record") or _base_record(state, "processing_error")
    record.setdefault("artifacts", {})["agent_trace"] = job_store.list_actions(message.id, db_path)
    record["artifacts"]["architecture"] = "llm_fixed_workflow"
    return record
