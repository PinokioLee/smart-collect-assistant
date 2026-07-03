"""에이전틱 흐름 테스트 — 구조화 추론 스텝 / 자가교정 검증 게이트 / 트레이스 증거.

모두 tmp_path 에 엑셀을 만들어 실행하므로 data/samples 잠금과 무관하며,
use_llm=False 로 결정론 경로를 고정해 오프라인·재현 가능하게 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from smart_collect.pipeline import run_collection
from smart_collect.state import ValidationRule
from smart_collect.tools import excel_tools as ex
from smart_collect.tools.self_correction import (
    _verify_proposal,
    run_self_correction,
)

COLS = ["부서명", "담당자", "요청시스템", "개선요청내용", "긴급도", "요청사유", "요청일자"]
SUBJECT = "2026년 6월 시스템 개선 요청 취합"
BODY = (
    "작성 항목은 부서명, 담당자, 요청시스템, 개선요청내용, 긴급도, 요청사유, 요청일자입니다.\n"
    "긴급도는 상/중/하. 요청일자는 YYYY-MM-DD. 부서명, 담당자, 요청시스템, 긴급도는 필수 입력."
)


@pytest.fixture
def submit_file(tmp_path: Path) -> str:
    rows = [
        ["영업1팀", "김영수", "ERP", "개선A", "중", "사유", "2026-06-03"],
        ["영업1팀", "이서연", "CRM", "개선B", "매우 급함", "사유", "2026/06/05"],  # 코드값+날짜 오류
        ["생산1팀", "", "MES", "개선C", "상", "사유", "2026-06-04"],  # 필수값 누락
    ]
    p = tmp_path / "submit.xlsx"
    pd.DataFrame(rows, columns=COLS).to_excel(p, index=False, engine="openpyxl")
    return str(p)


# ---------- 검증 게이트 단위 ----------

def test_verify_proposal_code_gate():
    assert _verify_proposal("허용되지 않은 코드값", "상", ["상", "중", "하"]) is True
    assert _verify_proposal("허용되지 않은 코드값", "긴급", ["상", "중", "하"]) is False


def test_verify_proposal_date_gate():
    assert _verify_proposal("날짜 형식 오류", "2026-06-05", []) is True
    assert _verify_proposal("날짜 형식 오류", "2026/06/05", []) is False  # 정규화 안 된 값
    assert _verify_proposal("날짜 형식 오류", "2026-13-40", []) is False  # 실제 날짜 아님


# ---------- 파이프라인: 구조화 추론 스텝 + 트레이스 ----------

def test_pipeline_emits_structured_steps(submit_file):
    state = run_collection("AGENTIC-TEST-1", SUBJECT, BODY, [submit_file], prefer_llm=False)
    phases = [s.phase for s in state.reasoning_steps]
    # 핵심 국면이 모두 기록돼야 한다
    for expected in ("PLAN", "BRANCH", "SELECT", "VALIDATE", "CRITIQUE", "RE-VALIDATE", "DONE"):
        assert expected in phases, f"{expected} 스텝 누락"
    # seq 는 1부터 연속
    assert [s.seq for s in state.reasoning_steps] == list(
        range(1, len(state.reasoning_steps) + 1)
    )


def test_pipeline_self_correction_deterministic(submit_file):
    """오프라인 경로: 코드값·날짜 오류가 결정론적으로 교정·채택된다."""
    state = run_collection("AGENTIC-TEST-2", SUBJECT, BODY, [submit_file], prefer_llm=False)
    sc = state.self_correction
    assert sc is not None
    assert sc.applied_corrections == 2  # 매우 급함→상, 2026/06/05→2026-06-05
    assert sc.accepted
    # 모든 교정은 결정론 게이트를 통과(verified)해야 한다
    assert all(c.verified for c in sc.corrections)
    # 오프라인 경로이므로 판단 주체는 규칙
    assert all(c.source == "rule" for c in sc.corrections)


def test_pipeline_writes_trace_evidence(submit_file):
    state = run_collection("AGENTIC-TEST-3", SUBJECT, BODY, [submit_file], prefer_llm=False)
    assert "json" in state.trace_files and "md" in state.trace_files
    json_path = Path(state.trace_files["json"])
    md_path = Path(state.trace_files["md"])
    assert json_path.exists() and md_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["request_id"] == "AGENTIC-TEST-3"
    assert payload["reasoning_steps"], "트레이스에 추론 스텝이 있어야 한다"

    md = md_path.read_text(encoding="utf-8")
    assert "단계별 추론 타임라인" in md
    assert "판단 주체" in md  # LLM/규칙 구분 컬럼


def test_supervisor_plan_offline_fallback(submit_file):
    """Azure 미사용(prefer_llm=False) 시 계획은 휴리스틱으로 채워진다."""
    state = run_collection("AGENTIC-TEST-4", SUBJECT, BODY, [submit_file], prefer_llm=False)
    assert state.supervisor_plan is not None
    assert state.supervisor_plan.get("source") == "heuristic"
