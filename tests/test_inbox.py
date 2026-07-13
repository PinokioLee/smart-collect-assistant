"""수신함 파이프라인(Phase A) 회귀 테스트.

mock 수신함 + 결정론 휴리스틱(prefer_llm=False)으로 분류/초안/중복방지/저장을
검증한다. Azure 키 없이 재현 가능하다.
"""

import pytest

from smart_collect import store
from smart_collect.inbox_pipeline import ingest_inbox
from smart_collect.tools import directory_tools
from smart_collect.tools.inbox_tools import MockInboxAdapter
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
    # 일반 메일(회식/뉴스레터) → general
    assert classify_heuristic(msgs["MOCK-INBOX-003"]).tier == "general"
    assert classify_heuristic(msgs["MOCK-INBOX-005"]).tier == "general"
    # 모호 → review(확인 필요)
    assert classify_heuristic(msgs["MOCK-INBOX-004"]).tier == "review"


def test_collection_label_is_correct():
    msgs = _by_id(MockInboxAdapter().list_new())
    c1 = classify_heuristic(msgs["MOCK-INBOX-001"])
    assert c1.label == "취합요청"
    assert classify_heuristic(msgs["MOCK-INBOX-003"]).label == "일반"


def test_directory_lookup_returns_contacts():
    contacts = directory_tools.lookup_recipients()
    assert len(contacts) == 3
    assert all({"name", "dept", "email"} <= set(c) for c in contacts)


def test_ingest_processes_and_builds_drafts(db):
    result = ingest_inbox(
        adapter=MockInboxAdapter(), db_path=db, prefer_llm=False
    )
    assert result["fetched"] == 5
    assert result["processed_new"] == 5
    assert result["skipped"] == 0
    # 2건 자동 초안, 1건 확인 필요, 2건 일반
    assert result["by_status"]["draft_ready"] == 2
    assert result["by_status"]["needs_review"] == 1
    assert result["by_status"]["general"] == 2


def test_auto_records_have_draft_and_recipients(db):
    ingest_inbox(adapter=MockInboxAdapter(), db_path=db, prefer_llm=False)
    ready = store.list_records(status="draft_ready", db_path=db)
    assert len(ready) == 2
    for r in ready:
        assert r["draft_subject"] and r["draft_body"]
        assert len(r["recipients"]) == 3  # 조직도 기반 수신자
        assert r["classification"] == "취합요청"


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
