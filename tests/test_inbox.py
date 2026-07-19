"""수신함 파이프라인(Phase A) 회귀 테스트.

mock 수신함 + 결정론 휴리스틱(prefer_llm=False)으로 분류/초안/중복방지/저장을
검증한다. Azure 키 없이 재현 가능하다.
"""

import pytest
from types import SimpleNamespace

import api as api_module
from smart_collect import store
from smart_collect.inbox_pipeline import ingest_inbox
from smart_collect.tools import directory_tools
from smart_collect.tools.inbox_tools import InboxMessage, MockInboxAdapter
from smart_collect.tools.mail_classifier import classify_heuristic


@pytest.fixture
def db(tmp_path):
    return tmp_path / "inbox_test.db"


def _by_id(msgs):
    return {m.id: m for m in msgs}


def test_mock_inbox_has_five_messages():
    msgs = MockInboxAdapter().list_new()
    assert len(msgs) == 5


def test_heuristic_classifies_collection_vs_general():
    msgs = _by_id(MockInboxAdapter().list_new())
    # 취합 요청(명확) → auto
    assert classify_heuristic(msgs["MOCK-INBOX-001"]).tier == "auto"
    assert classify_heuristic(msgs["MOCK-INBOX-002"]).tier == "auto"
    # 일반 메일(회식) / 스팸(뉴스레터)
    assert classify_heuristic(msgs["MOCK-INBOX-003"]).tier == "general"
    assert classify_heuristic(msgs["MOCK-INBOX-005"]).tier == "quarantine"
    assert classify_heuristic(msgs["MOCK-INBOX-005"]).category == "spam"
    # 모호 → review(확인 필요)
    assert classify_heuristic(msgs["MOCK-INBOX-004"]).tier == "review"


def test_collection_label_is_correct():
    msgs = _by_id(MockInboxAdapter().list_new())
    c1 = classify_heuristic(msgs["MOCK-INBOX-001"])
    assert c1.label == "취합업무메일"
    assert c1.intent == "request"
    assert classify_heuristic(msgs["MOCK-INBOX-003"]).label == "일반메일"


def test_job_id_question_is_classified_as_collection():
    message = InboxMessage(
        id="QUESTION-1", sender="user@company.com",
        subject="[SC-20260719] 문의", body="마감이 언제인가요?",
    )
    result = classify_heuristic(message)
    assert result.category == "collection"
    assert result.intent == "question"


def test_directory_lookup_returns_contacts():
    contacts = directory_tools.lookup_recipients()
    assert len(contacts) == 3
    assert all({"name", "dept", "email"} <= set(c) for c in contacts)


def test_directory_can_be_loaded_from_csv(tmp_path, monkeypatch):
    directory = tmp_path / "directory.csv"
    directory.write_text(
        "name,dept,email\n이개발,IT팀,dev@corp.example\n중복,IT팀,dev@corp.example\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(directory_tools, "settings", SimpleNamespace(directory_file=str(directory)))
    contacts = directory_tools.lookup_recipients(["IT팀"])
    assert contacts == [{"name": "이개발", "dept": "IT팀", "email": "dev@corp.example"}]


def test_invalid_configured_directory_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        directory_tools, "settings",
        SimpleNamespace(directory_file=str(tmp_path / "missing.csv")),
    )
    assert directory_tools.lookup_recipients() == []


def test_recipient_defaults_to_original_sender_and_cc():
    message = InboxMessage(
        id="REPLY-ALL-1",
        sender="요청자 <requester@company.com>",
        cc=["참조자 <observer@company.com>", "other@company.com"],
        subject="월 실적 취합 요청",
        body="첨부한 양식에 작성해 주세요.",
    )
    recipients, source = directory_tools.resolve_collection_recipients(message)
    assert source == "original_sender_cc"
    assert [item["email"] for item in recipients] == [
        "requester@company.com", "observer@company.com", "other@company.com",
    ]


def test_requester_recipients_preserve_to_and_cc_roles():
    message = InboxMessage(
        id="REQUESTER-ROLES",
        sender="팀장 <manager@company.com>",
        cc=["기획담당 <planner@company.com>"],
        subject="월 실적 취합 요청",
        body="W/G 리더에게 취합해 주세요.",
    )
    requesters = directory_tools.resolve_requester_recipients(message)
    assert requesters == [
        {
            "name": "팀장", "dept": "원본 메일", "email": "manager@company.com",
            "recipient_type": "to",
        },
        {
            "name": "기획담당", "dept": "원본 메일", "email": "planner@company.com",
            "recipient_type": "cc",
        },
    ]


def test_explicit_department_uses_directory_instead_of_reply_all():
    message = InboxMessage(
        id="TARGET-1",
        sender="요청자 <requester@company.com>",
        cc=["observer@company.com"],
        subject="영업팀 대상 월 실적 취합 요청",
        body="제출 대상: 영업팀",
    )
    recipients, source = directory_tools.resolve_collection_recipients(message)
    assert source == "directory_explicit_target"
    assert [item["dept"] for item in recipients] == ["영업팀"]


def test_ingest_processes_and_builds_drafts(db):
    result = ingest_inbox(
        adapter=MockInboxAdapter(), db_path=db, prefer_llm=False
    )
    assert result["fetched"] == 5
    assert result["processed_new"] == 5
    assert result["skipped"] == 0
    # 2건 자동 초안, 1건 확인 필요, 1건 일반, 1건 격리
    assert result["by_status"]["draft_ready"] == 2
    assert result["by_status"]["needs_review"] == 1
    assert result["by_status"]["general"] == 1
    assert result["by_status"]["quarantined"] == 1


def test_auto_records_have_draft_and_recipients(db):
    ingest_inbox(adapter=MockInboxAdapter(), db_path=db, prefer_llm=False)
    ready = store.list_records(status="draft_ready", db_path=db)
    assert len(ready) == 2
    for r in ready:
        assert r["draft_subject"] and r["draft_body"]
        assert len(r["recipients"]) == 3  # 조직도 기반 수신자
        assert r["classification"] == "취합업무메일"
        assert r["intent"] == "request"
        assert r["decision"]["action"] == "review"  # 테스트 기본은 자동발송 OFF
        assert r["artifacts"]["strategy"] in {"use_attached", "generate"}


def test_ingest_is_idempotent_dedup(db):
    ingest_inbox(adapter=MockInboxAdapter(), db_path=db, prefer_llm=False)
    second = ingest_inbox(adapter=MockInboxAdapter(), db_path=db, prefer_llm=False)
    # 두 번째 실행은 모두 이미 처리됨 → 새로 처리 0, 건너뜀 5
    assert second["processed_new"] == 0
    assert second["skipped"] == 5


def test_auto_records_carry_grounding_and_sources(db):
    ingest_inbox(adapter=MockInboxAdapter(), db_path=db, prefer_llm=False)
    ready = store.list_records(status="draft_ready", db_path=db)
    for r in ready:
        assert "checks" in r["grounding"]  # 근거 검증 리포트 존재
        assert isinstance(r["sources"], list)  # RAG 근거 문서 목록
    # 명확한 취합요청(001, 작성 항목 명시)은 근거 완전(flags 없음)
    m1 = store.get_record("MOCK-INBOX-001", db_path=db)
    assert m1["grounding"]["flags"] == []
    # 002(작성 항목 미명시)는 '작성 항목' 근거 없음으로 플래그
    m2 = store.get_record("MOCK-INBOX-002", db_path=db)
    assert "작성 항목" in m2["grounding"]["flags"]


def test_mark_sent_updates_status(db):
    ingest_inbox(adapter=MockInboxAdapter(), db_path=db, prefer_llm=False)
    ready = store.list_records(status="draft_ready", db_path=db)
    mid = ready[0]["message_id"]
    assert store.mark_sent(mid, "SENT-123", db_path=db) is True
    rec = store.get_record(mid, db_path=db)
    assert rec["status"] == "sent" and rec["sent"] is True


def test_sent_mail_can_be_resent_to_new_extra_recipient(monkeypatch):
    record = {
        "message_id": "SENT-1",
        "status": "sent",
        "recipients": [{"name": "요청자", "dept": "원본 메일", "email": "requester@company.com"}],
        "draft_subject": "[취합 요청] 월 실적",
        "draft_body": "작성 후 회신해 주세요.",
        "artifacts": {"attachment_paths": []},
    }
    captured = {}
    monkeypatch.setattr(api_module.store, "get_record", lambda _: record)
    monkeypatch.setattr(api_module.store, "upsert_record", lambda value: captured.setdefault("saved", value))
    monkeypatch.setattr(api_module, "send_email", lambda request: {
        "status": "mock_sent", "message_id": "EXTRA-1", "recipients": request.to,
    })
    response = api_module.inbox_send("SENT-1", {
        "extra_recipients": ["requester@company.com", "new@company.com"],
    })
    assert response["additional_only"] is True
    assert response["send_result"]["recipients"] == ["new@company.com"]
    assert captured["saved"]["artifacts"]["additional_sends"][0]["recipients"] == ["new@company.com"]


def test_final_reply_approval_marks_job_completed_and_allows_manual_edits(monkeypatch):
    record = {
        "message_id": "FINAL-APPROVAL",
        "status": "draft_ready",
        "intent": "completion",
        "recipients": [
            {"name": "팀장", "dept": "요청자", "email": "manager@company.com"},
            {"name": "참조", "dept": "요청자", "email": "observer@company.com"},
        ],
        "draft_subject": "기존 제목",
        "draft_body": "기존 본문",
        "artifacts": {
            "job_id": "SC-FINAL-APPROVAL", "attachment_paths": [],
            "cc_recipients": ["observer@company.com"],
            "reply_context": {"thread_id": "SOURCE-THREAD"},
        },
    }
    captured = {}
    monkeypatch.setattr(api_module.store, "get_record", lambda _: record)
    monkeypatch.setattr(api_module.store, "upsert_record", lambda value: captured.setdefault("saved", value))
    monkeypatch.setattr(api_module.store, "mark_sent", lambda *a, **k: True)
    monkeypatch.setattr(api_module.job_store, "update_job", lambda *a, **k: captured.setdefault("job", (a, k)))

    def fake_send(request):
        captured["request"] = request
        return {"status": "mock_sent", "message_id": "FINAL-SENT", "thread_id": request.thread_id}

    monkeypatch.setattr(api_module, "send_email", fake_send)
    response = api_module.inbox_send("FINAL-APPROVAL", {
        "recipients": ["manager@company.com", "observer@company.com"],
        "subject": "수정한 최종 제목",
        "body": "수정한 최종 본문",
    })

    assert response["additional_only"] is False
    assert captured["request"].to == ["manager@company.com"]
    assert captured["request"].cc == ["observer@company.com"]
    assert captured["request"].subject == "수정한 최종 제목"
    assert captured["request"].body == "수정한 최종 본문"
    assert captured["job"][1]["status"] == "completed"
    assert captured["job"][1]["final_reply_status"] == "sent"
