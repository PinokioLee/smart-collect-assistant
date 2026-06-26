"""전체 범위 기능 테스트 — 공통항목 일괄수정 / 제출추적 / 가이드·리마인드 폴백.

LLM 호출은 비결정적이므로 폴백 경로(결정론)를 검증한다.
"""

from smart_collect.sample_data import generate_samples
from smart_collect.state import ExtractedRequirements
from smart_collect.tools.excel_tools import load_excel_files, update_common_fields
from smart_collect.tools.guide_tools import _guide_fallback, generate_reminder_message
from smart_collect.tools.submission_tools import (
    SAMPLE_RECIPIENTS,
    submissions_from_files,
    track_submission_status,
)


# ---------- 공통항목 일괄수정 (#7) ----------

def test_update_existing_value():
    ex = generate_samples()["excels"]
    r = update_common_fields(ex, "긴급도", "중", old_value="상")
    assert r["update_count"] == 4  # 샘플의 '상' 4건
    assert len(r["updated_files"]) == 3


def test_update_add_missing_column():
    ex = generate_samples()["excels"]
    r = update_common_fields(ex, "취합월", "2026-06")
    assert r["update_count"] == 11  # 전체 행
    chk = load_excel_files([r["updated_files"][0]])[0]
    assert "취합월" in chk.df.columns
    assert chk.df["취합월"].iloc[0] == "2026-06"


def test_update_preserves_original():
    ex = generate_samples()["excels"]
    update_common_fields(ex, "취합월", "2026-06")
    orig = load_excel_files([ex[0]])[0]
    assert "취합월" not in orig.df.columns  # 원본 불변


def test_update_missing_column_no_add():
    ex = generate_samples()["excels"]
    r = update_common_fields(ex, "없는항목", "x", add_if_missing=False)
    assert r["update_count"] == 0
    assert len(r["error_list"]) == 3


# ---------- 제출 현황 추적 (#5) ----------

def test_track_submission_status():
    ex = generate_samples()["excels"]  # 영업/생산/품질 (물류 없음)
    subs = submissions_from_files(ex, submitted_at="2026-06-12 14:00")
    st = track_submission_status(SAMPLE_RECIPIENTS, subs, deadline="2026-06-12 17:00")
    assert st["submission_rate"] == 75.0
    assert len(st["missing_list"]) == 1
    assert st["missing_list"][0]["dept"] == "물류팀"
    assert len(st["late_list"]) == 0


def test_track_late_submission():
    ex = generate_samples()["excels"]
    subs = submissions_from_files(ex, submitted_at="2026-06-12 19:00")  # 마감 후
    st = track_submission_status(SAMPLE_RECIPIENTS, subs, deadline="2026-06-12 17:00")
    assert len(st["late_list"]) == 3  # 제출 3건 모두 지연


# ---------- 가이드 / 리마인드 폴백 (#2, #6) ----------

def test_guide_fallback():
    req = ExtractedRequirements(
        request_title="테스트 취합", deadline="2026-06-12 17:00",
        required_fields=["부서명", "담당자"],
    )
    g = _guide_fallback(req)
    assert g["guide_title"]
    assert "부서명" in g["guide_body"]
    assert len(g["field_instructions"]) == 2


def test_reminder_fallback_no_llm(monkeypatch):
    # chat 을 None 반환으로 강제 → 폴백 경로 검증
    import smart_collect.tools.guide_tools as gt
    monkeypatch.setattr(gt, "chat", lambda *a, **k: None)
    rem = gt.generate_reminder_message(
        [{"name": "홍길동", "dept": "영업팀"}], "2026-06-12 17:00"
    )
    assert "재안내" in rem["reminder_mail_subject"]
    assert rem["reminder_mail_body"]
