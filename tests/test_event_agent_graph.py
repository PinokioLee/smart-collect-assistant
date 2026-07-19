"""이벤트 기반 Supervisor + Worker Agent의 대표 업무 시나리오."""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from smart_collect import autonomous_graph, inbox_pipeline, job_store, llm
from smart_collect.deadline_agent import run_deadline_agent
from smart_collect.state import ColumnSpec, ExtractedRequirements, TemplateSpec
from smart_collect.tools import advanced_rag
from smart_collect.tools.inbox_tools import InboxMessage
from smart_collect.tools.mail_classifier import ClassificationResult


def _cls(category, intent="other", confidence=0.98, tier="auto"):
    return ClassificationResult(
        category=category, intent=intent, confidence=confidence,
        tier=tier, source="test",
    )


def _message(mid, subject, body="", attachments=None, paths=None, sender="user@company.com"):
    return InboxMessage(
        id=mid, sender=sender, subject=subject, body=body,
        attachments=attachments or [], attachment_paths=paths or [],
        received_at="2026-07-19 10:00",
    )


def _xlsx(path: Path, rows):
    pd.DataFrame(rows, columns=["부서명", "담당자", "금액"]).to_excel(path, index=False)
    return str(path)


def _job(db, tmp_path, *, job_id="SC-JOB", recipients=None, deadline="2026-07-20 17:00"):
    template = tmp_path / f"{job_id}_template.xlsx"
    _xlsx(template, [])
    return job_store.create_job({
        "job_id": job_id, "source_thread_id": "THREAD-SC-JOB",
        "source_rfc_message_id": "<manager-request@company.com>",
        "title": "월간 실적 취합", "deadline": deadline,
        "recipients": recipients or [{"name": "사용자", "dept": "영업", "email": "user@company.com"}],
        "requester_recipients": [
            {"name": "팀장", "dept": "요청자", "email": "manager@company.com", "recipient_type": "to"},
        ],
        "required_fields": ["부서명", "담당자", "금액"],
        "validation_rule": {
            "required_columns": ["부서명", "담당자", "금액"],
            "number_columns": ["금액"], "date_columns": [], "code_rules": {}, "duplicate_keys": [],
        },
        "template_path": str(template), "status": "collecting",
    }, db)


def test_01_general_mail_is_archived(tmp_path, monkeypatch):
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("general", tier="general"))
    record = autonomous_graph.run_mail_event(_message("GEN", "사내 공지"), db_path=tmp_path / "db.sqlite", prefer_llm=False)
    assert record["status"] == "general"
    assert record["artifacts"]["agent_trace"][-1]["agent"] == "General Mail Agent"


def test_02_spam_and_prompt_injection_are_quarantined(tmp_path, monkeypatch):
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: ClassificationResult(
        category="spam", confidence=0.99, tier="quarantine", risk_flags=["prompt_injection"]
    ))
    record = autonomous_graph.run_mail_event(_message("SPAM", "광고"), db_path=tmp_path / "db.sqlite", prefer_llm=False)
    assert record["status"] == "quarantined"


def test_03_request_creates_job_template_and_draft(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "request"))
    req = ExtractedRequirements(
        request_title="월간 실적", deadline="2026-07-30 17:00",
        required_fields=["부서명", "담당자", "금액"],
    )
    spec = TemplateSpec(title="월간 실적", columns=[
        ColumnSpec(name="부서명", required=True), ColumnSpec(name="담당자", required=True),
        ColumnSpec(name="금액", dtype="number", required=True),
    ])
    generated = tmp_path / "generated.xlsx"
    _xlsx(generated, [])
    monkeypatch.setattr(inbox_pipeline, "analyze_collection_email", lambda *a, **k: req)
    monkeypatch.setattr(inbox_pipeline, "design_template_from_intent", lambda *a, **k: spec)
    monkeypatch.setattr(inbox_pipeline, "build_and_save_template", lambda s: {
        "template_id": "TPL-REQ", "filename": "generated.xlsx", "excel_path": str(generated),
        "download": "/api/download-template/TPL-REQ",
        "validation_rule": {"required_columns": ["부서명", "담당자", "금액"], "number_columns": ["금액"]},
    })
    monkeypatch.setattr(advanced_rag, "build_rag_context", lambda *a, **k: {
        "grounding": {"flags": [], "score": 1.0}, "sources": [], "retrieved": [],
    })
    record = autonomous_graph.run_mail_event(
        _message("REQ-1", "[취합 요청] 월간 실적", "금액을 7월 30일까지 작성 요청합니다."),
        db_path=db, prefer_llm=False,
    )
    assert record["status"] == "draft_ready"
    assert record["artifacts"]["job_id"] == "SC-REQ-1"
    created_job = job_store.get_job("SC-REQ-1", db)
    assert created_job["status"] == "awaiting_approval"
    assert created_job["requester_recipients"][0]["email"] == "user@company.com"


def test_04_valid_submission_is_accepted(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(autonomous_graph, "DATA_DIR", tmp_path)
    path = _xlsx(tmp_path / "valid.xlsx", [["영업", "홍길동", "1000"]])
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "submission"))
    record = autonomous_graph.run_mail_event(
        _message("SUB-OK", "[SC-JOB] 제출합니다", attachments=["valid.xlsx"], paths=[path]),
        db_path=db, prefer_llm=False, auto_send_enabled=False,
    )
    assert record["status"] == "draft_ready"
    assert record["intent"] == "completion"
    assert job_store.list_submissions("SC-JOB", db)[0]["status"] == "accepted"


def test_05_invalid_submission_creates_rejection_mail(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    path = _xlsx(tmp_path / "invalid.xlsx", [["영업", "", "not-number"]])
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "submission"))
    record = autonomous_graph.run_mail_event(
        _message("SUB-BAD", "[SC-JOB] 제출합니다", attachments=["invalid.xlsx"], paths=[path]),
        db_path=db, prefer_llm=False,
    )
    assert record["status"] == "draft_ready"
    types = {e["error_type"] for e in record["artifacts"]["validation_errors"]}
    assert {"필수값 누락", "숫자 형식 오류"} <= types
    assert "수정 요청" in record["draft_subject"]


def test_06_corrected_resubmission_is_revalidated(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(autonomous_graph, "DATA_DIR", tmp_path)
    bad = _xlsx(tmp_path / "bad.xlsx", [["영업", "", "x"]])
    good = _xlsx(tmp_path / "good.xlsx", [["영업", "홍길동", "1200"]])
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda msg, **k: _cls(
        "collection", "correction" if msg.id == "CORRECT" else "submission"
    ))
    autonomous_graph.run_mail_event(
        _message("FIRST", "[SC-JOB] 제출", attachments=["bad.xlsx"], paths=[bad]),
        db_path=db, prefer_llm=False,
    )
    corrected = autonomous_graph.run_mail_event(
        _message("CORRECT", "[SC-JOB] 수정본 재제출", attachments=["good.xlsx"], paths=[good]),
        db_path=db, prefer_llm=False, auto_send_enabled=False,
    )
    assert corrected["status"] == "draft_ready"
    assert corrected["intent"] == "completion"
    assert {s["status"] for s in job_store.list_submissions("SC-JOB", db)} == {"rejected", "accepted"}


def test_07_question_is_grounded_and_waits_for_approval_offline(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "question"))
    record = autonomous_graph.run_mail_event(
        _message("Q-1", "[SC-JOB] 작성 문의", "마감이 언제인가요?"),
        db_path=db, prefer_llm=False,
    )
    assert record["status"] == "draft_ready"
    assert "2026-07-20" in record["draft_body"]
    assert record["decision"]["action"] == "review"


def test_08_deadline_extension_always_requires_approval(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "extension"))
    record = autonomous_graph.run_mail_event(
        _message("EXT", "[SC-JOB] 기한 연장 요청", "하루 연장 가능할까요?"),
        db_path=db, prefer_llm=False,
    )
    assert record["status"] == "needs_review"
    assert "policy_exception" in record["decision"]["risk_flags"]


def test_09_worker_failure_is_observed_and_replanned(tmp_path, monkeypatch):
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "submission"))
    record = autonomous_graph.run_mail_event(
        _message("ORPHAN", "출처 불명 제출", attachments=["x.xlsx"]),
        db_path=tmp_path / "db.sqlite", prefer_llm=False,
    )
    assert record["status"] == "needs_review"
    actions = [a["action"] for a in record["artifacts"]["agent_trace"]]
    assert "observe_worker_result" in actions
    assert "handoff_to_human" in actions


def test_10_deadline_tick_drafts_reminder_for_missing_submitter(tmp_path):
    db = tmp_path / "db.sqlite"
    now = datetime(2026, 7, 19, 10, 0)
    _job(db, tmp_path, deadline=(now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"))
    result = run_deadline_agent(
        now=now, db_path=db, prefer_llm=False, auto_send_enabled=False,
    )
    assert result["drafted"] == 1
    assert result["details"][0]["missing"] == 1


def test_11_all_valid_submissions_trigger_merge(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path, job_id="SC-MERGE")
    monkeypatch.setattr(autonomous_graph, "DATA_DIR", tmp_path)
    path = _xlsx(tmp_path / "merge.xlsx", [["영업", "홍길동", "1000"]])
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "submission"))
    record = autonomous_graph.run_mail_event(
        _message("MERGE", "[SC-MERGE] 제출합니다", attachments=["merge.xlsx"], paths=[path]),
        db_path=db, prefer_llm=False, auto_send_enabled=False,
    )
    assert Path(record["artifacts"]["merged_file"]).exists()
    assert record["intent"] == "completion"
    assert record["recipients"][0]["email"] == "manager@company.com"
    assert job_store.get_job("SC-MERGE", db)["status"] == "awaiting_final_reply"


def test_12_transient_worker_failure_retries_once_then_succeeds(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "submission"))
    calls = {"count": 0}

    def flaky_worker(state):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "outcome": "failure",
                "observation": {"error": "temporary service timeout"},
                "terminal": False,
            }
        return {
            "record": autonomous_graph._base_record(state, "submission_accepted"),
            "outcome": "success",
            "terminal": True,
        }

    monkeypatch.setattr(autonomous_graph, "_submission_worker", flaky_worker)
    record = autonomous_graph.run_mail_event(
        _message("TRANSIENT", "[SC-JOB] 제출", attachments=["retry.xlsx"]),
        db_path=db,
        prefer_llm=False,
    )
    actions = job_store.list_actions("TRANSIENT", db)
    assert calls["count"] == 2
    assert record["status"] == "submission_accepted"
    assert any(a["action"] == "observe_worker_result" and a["outcome"] == "retry" for a in actions)
    assert sum(a["action"] == "select_next_action" for a in actions) == 2


def test_13_supervisor_considers_all_collection_capabilities():
    routes = autonomous_graph._allowed_routes(_cls("collection", "question"))
    assert routes == [
        "request_worker", "submission_worker", "qa_worker",
        "extension_worker", "human_review",
    ]


def test_14_policy_gate_blocks_incompatible_llm_route(tmp_path, monkeypatch):
    monkeypatch.setattr(
        autonomous_graph, "classify_message",
        lambda *a, **k: _cls("collection", "question"),
    )
    monkeypatch.setattr(
        autonomous_graph, "_llm_route",
        lambda state, allowed: ("submission_worker", "첨부를 검증하겠음"),
    )
    record = autonomous_graph.run_mail_event(
        _message("ROUTE-GATE", "작성 문의", "마감이 언제인가요?"),
        db_path=tmp_path / "db.sqlite", prefer_llm=True,
    )
    assert record["status"] == "needs_review"
    actions = job_store.list_actions("ROUTE-GATE", tmp_path / "db.sqlite")
    decision = next(a for a in actions if a["action"] == "select_next_action")
    assert decision["detail"]["route"] == "human_review"
    assert "route_intent_mismatch" in decision["detail"]["reason"]


def test_15_grounded_participant_question_is_auto_replied_in_same_thread(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(
        autonomous_graph, "classify_message",
        lambda *a, **k: _cls("collection", "question", confidence=0.98),
    )
    monkeypatch.setattr(autonomous_graph, "_llm_route", lambda *a, **k: ("qa_worker", "질문 답변"))
    monkeypatch.setattr(autonomous_graph, "settings", type("Settings", (), {
        "azure_ready": True, "auto_send_enabled": True,
        "auto_send_allowed_domains": ("company.com",), "auto_send_min_confidence": 0.90,
    })())
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "body": "제출 마감은 2026년 7월 20일 17시입니다.",
        "answerable": True, "requires_review": False,
        "used_fact_keys": ["마감"], "reason": "Job 마감 정보로 답변",
    })
    sent = {}
    def fake_send(request):
        sent["request"] = request
        return {"status": "mock_sent", "message_id": "QA-AUTO-1", "thread_id": request.thread_id}
    monkeypatch.setattr(inbox_pipeline, "send_email", fake_send)
    record = autonomous_graph.run_mail_event(
        InboxMessage(
            id="QA-AUTO", thread_id="THREAD-SC-JOB",
            rfc_message_id="<question-1@company.com>", references="<request-1@company.com>",
            sender="사용자 <user@company.com>", subject="Re: 월간 실적 취합",
            body="제출 마감은 언제인가요?",
        ),
        db_path=db, prefer_llm=True, auto_send_enabled=True,
    )
    assert record["status"] == "sent"
    assert record["decision"]["action"] == "auto_send"
    assert sent["request"].thread_id == "THREAD-SC-JOB"
    assert sent["request"].in_reply_to == "<question-1@company.com>"
    assert record["artifacts"]["answer_grounding"]["used_fact_keys"] == ["마감"]


def test_16_question_from_non_participant_requires_review(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "question"))
    monkeypatch.setattr(autonomous_graph, "_llm_route", lambda *a, **k: ("qa_worker", "질문 답변"))
    monkeypatch.setattr(autonomous_graph, "settings", type("Settings", (), {
        "azure_ready": True, "auto_send_enabled": True,
        "auto_send_allowed_domains": ("company.com",), "auto_send_min_confidence": 0.90,
    })())
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "body": "제출 마감은 17시입니다.", "answerable": True,
        "requires_review": False, "used_fact_keys": ["마감"], "reason": "마감 근거",
    })
    record = autonomous_graph.run_mail_event(
        _message("QA-OUT", "[SC-JOB] 작성 문의", "마감은 언제인가요?", sender="other@company.com"),
        db_path=db, prefer_llm=True, auto_send_enabled=True,
    )
    assert record["status"] == "draft_ready"
    assert record["decision"]["action"] == "review"
    assert "sender_not_job_participant" in record["decision"]["risk_flags"]


def test_17_policy_change_question_never_auto_replies(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    monkeypatch.setattr(autonomous_graph, "classify_message", lambda *a, **k: _cls("collection", "question"))
    monkeypatch.setattr(autonomous_graph, "_llm_route", lambda *a, **k: ("qa_worker", "질문 답변"))
    monkeypatch.setattr(autonomous_graph, "settings", type("Settings", (), {
        "azure_ready": True, "auto_send_enabled": True,
        "auto_send_allowed_domains": ("company.com",), "auto_send_min_confidence": 0.90,
    })())
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "body": "변경 가능합니다.", "answerable": True,
        "requires_review": False, "used_fact_keys": ["양식"], "reason": "양식 근거",
    })
    record = autonomous_graph.run_mail_event(
        _message("QA-POLICY", "[SC-JOB] 문의", "양식을 바꿔 제출해도 되나요?"),
        db_path=db, prefer_llm=True, auto_send_enabled=True,
    )
    assert record["decision"]["action"] == "review"
    assert "policy_change_or_exception_question" in record["decision"]["risk_flags"]


def test_18_thread_context_routes_short_offline_reply_to_qa(tmp_path):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    record = autonomous_graph.run_mail_event(
        InboxMessage(
            id="QA-THREAD", thread_id="THREAD-SC-JOB", sender="user@company.com",
            subject="Re: 월간 실적", body="작성 기준을 어떻게 적용하나요?",
        ),
        db_path=db, prefer_llm=False, auto_send_enabled=False,
    )
    assert record["intent"] == "question"
    assert record["status"] == "draft_ready"
    assert record["artifacts"]["job_id"] == "SC-JOB"


def test_19_outbound_gmail_thread_can_find_collection_job(tmp_path):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path)
    job_store.update_job("SC-JOB", outbound_thread_id="GMAIL-OUTBOUND-THREAD", db_path=db)
    found = job_store.find_job_for_message("제목이 변경된 질문", "GMAIL-OUTBOUND-THREAD", db)
    assert found and found["job_id"] == "SC-JOB"


def test_20_gmail_submission_runs_safe_self_correction_and_merges_corrected_copy(
    tmp_path, monkeypatch,
):
    db = tmp_path / "db.sqlite"
    template = tmp_path / "quality_template.xlsx"
    pd.DataFrame(columns=["부서명", "담당자", "제출일자", "긴급도"]).to_excel(
        template, index=False,
    )
    job_store.create_job({
        "job_id": "SC-QUALITY", "source_thread_id": "THREAD-QUALITY",
        "source_rfc_message_id": "<quality-request@company.com>",
        "title": "품질 취합", "deadline": "2026-07-30 17:00",
        "recipients": [{"name": "사용자", "dept": "영업", "email": "user@company.com"}],
        "requester_recipients": [
            {"name": "팀장", "dept": "요청자", "email": "manager@company.com", "recipient_type": "to"},
        ],
        "required_fields": ["부서명", "담당자", "제출일자", "긴급도"],
        "validation_rule": {
            "required_columns": ["부서명", "담당자", "제출일자", "긴급도"],
            "date_columns": ["제출일자"], "number_columns": [],
            "code_rules": {"긴급도": ["상", "중", "하"]}, "duplicate_keys": [],
        },
        "template_path": str(template), "status": "collecting",
    }, db)
    submitted = tmp_path / "quality_submission.xlsx"
    pd.DataFrame([{
        "부서명": "영업", "담당자": "홍길동",
        "제출일자": "2026/07/20", "긴급도": "매우 급함",
    }]).to_excel(submitted, index=False)
    monkeypatch.setattr(autonomous_graph, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        autonomous_graph, "classify_message",
        lambda *a, **k: _cls("collection", "submission"),
    )

    record = autonomous_graph.run_mail_event(
        InboxMessage(
            id="QUALITY-SUB", thread_id="THREAD-QUALITY", sender="user@company.com",
            subject="[SC-QUALITY] 제출합니다", body="자가교정 가능한 제출본입니다.",
            attachments=[submitted.name],
            attachment_paths=[str(submitted)],
        ),
        db_path=db, prefer_llm=False, auto_send_enabled=False,
    )

    quality = record["artifacts"]["quality_pipeline"]
    assert record["status"] == "draft_ready"
    assert record["intent"] == "completion"
    assert quality["rule_source"] == "job_contract"
    assert quality["self_correction"]["accepted"] is True
    assert quality["self_correction"]["applied_corrections"] == 2
    corrected_path = Path(quality["corrected_submission_paths"][0])
    assert corrected_path.exists() and corrected_path != submitted
    merged = pd.read_excel(record["artifacts"]["merged_file"], dtype=str)
    assert merged.loc[0, "제출일자"] == "2026-07-20"
    assert merged.loc[0, "긴급도"] == "상"


def test_21_completion_report_auto_replies_to_original_requester(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path, job_id="SC-FINAL")
    monkeypatch.setattr(autonomous_graph, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        autonomous_graph, "classify_message",
        lambda *a, **k: _cls("collection", "submission"),
    )
    monkeypatch.setattr(autonomous_graph, "settings", type("Settings", (), {
        "azure_ready": False,
        "auto_send_enabled": True,
        "auto_send_allowed_domains": ("company.com",),
        "auto_send_min_confidence": 0.90,
    })())
    captured = {}

    def fake_send(request):
        captured["request"] = request
        return {
            "status": "mock_sent", "message_id": "FINAL-MAIL-1",
            "thread_id": request.thread_id, "recipients": request.to,
        }

    monkeypatch.setattr(inbox_pipeline, "send_email", fake_send)
    path = _xlsx(tmp_path / "final.xlsx", [["영업", "홍길동", "1000"]])
    record = autonomous_graph.run_mail_event(
        _message("FINAL-SUB", "[SC-FINAL] 제출합니다", attachments=["final.xlsx"], paths=[path]),
        db_path=db, prefer_llm=False, auto_send_enabled=True,
    )

    job = job_store.get_job("SC-FINAL", db)
    assert record["status"] == "sent"
    assert record["intent"] == "completion"
    assert record["artifacts"]["final_validation"]["error_rows"] == 0
    assert Path(record["artifacts"]["merged_file"]).exists()
    assert captured["request"].to == ["manager@company.com"]
    assert captured["request"].thread_id == "THREAD-SC-JOB"
    assert captured["request"].in_reply_to == "<manager-request@company.com>"
    assert job["status"] == "completed"
    assert job["final_reply_status"] == "sent"
    assert job["final_reply_message_id"] == "FINAL-MAIL-1"


def test_22_cross_file_duplicate_blocks_completion_and_requests_rework(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path, job_id="SC-DUP", recipients=[
        {"name": "작성자1", "dept": "WG1", "email": "user1@company.com"},
        {"name": "작성자2", "dept": "WG2", "email": "user2@company.com"},
    ])
    job = job_store.get_job("SC-DUP", db)
    rule = dict(job["validation_rule"])
    rule["duplicate_keys"] = ["부서명"]
    job_store.create_job({**job, "validation_rule": rule}, db)
    monkeypatch.setattr(autonomous_graph, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        autonomous_graph, "classify_message",
        lambda *a, **k: _cls("collection", "submission"),
    )
    first = _xlsx(tmp_path / "wg1.xlsx", [["공통부서", "홍길동", "1000"]])
    second = _xlsx(tmp_path / "wg2.xlsx", [["공통부서", "김영희", "2000"]])

    partial = autonomous_graph.run_mail_event(
        _message("DUP-1", "[SC-DUP] 제출", attachments=["wg1.xlsx"], paths=[first], sender="user1@company.com"),
        db_path=db, prefer_llm=False,
    )
    blocked = autonomous_graph.run_mail_event(
        _message("DUP-2", "[SC-DUP] 제출", attachments=["wg2.xlsx"], paths=[second], sender="user2@company.com"),
        db_path=db, prefer_llm=False,
    )

    assert partial["status"] == "submission_accepted"
    assert blocked["status"] == "draft_ready"
    assert "final_validation_failed" in blocked["decision"]["risk_flags"]
    assert blocked["recipients"][0]["email"] == "user2@company.com"
    assert job_store.get_job("SC-DUP", db)["status"] == "partial"
    statuses = {item["sender"]: item["status"] for item in job_store.list_submissions("SC-DUP", db)}
    assert statuses == {"user1@company.com": "accepted", "user2@company.com": "rejected"}


def test_23_unexpected_submitter_never_counts_toward_completion(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _job(db, tmp_path, job_id="SC-EXPECTED", recipients=[
        {"name": "작성자", "dept": "WG", "email": "expected@company.com"},
    ])
    path = _xlsx(tmp_path / "unexpected.xlsx", [["영업", "홍길동", "1000"]])
    monkeypatch.setattr(
        autonomous_graph, "classify_message",
        lambda *a, **k: _cls("collection", "submission"),
    )
    record = autonomous_graph.run_mail_event(
        _message(
            "UNEXPECTED", "[SC-EXPECTED] 제출", attachments=["unexpected.xlsx"],
            paths=[path], sender="other@company.com",
        ),
        db_path=db, prefer_llm=False,
    )
    assert record["status"] == "needs_review"
    assert job_store.list_submissions("SC-EXPECTED", db) == []
