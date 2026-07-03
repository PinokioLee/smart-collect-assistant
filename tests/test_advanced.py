"""고급 기법(ToT, Self-Correction) 및 파이프라인 통합 테스트."""

import pytest

from smart_collect.sample_data import generate_samples
from smart_collect.state import ExtractedRequirements, ValidationRule
from smart_collect.tools import excel_tools as ex
from smart_collect.tools.self_correction import (
    _map_code_value,
    _normalize_date,
    run_self_correction,
)
from smart_collect.tools.tot_rules import (
    generate_candidates,
    select_rules_with_tot,
)


# ---------- Self-Correction 단위 ----------

@pytest.mark.parametrize("raw,expected", [
    ("2026/06/05", "2026-06-05"),
    ("2026.06.05", "2026-06-05"),
    ("06/05/2026", "2026-06-05"),
    ("2026/6/5", "2026-06-05"),
    ("20260605", "2026-06-05"),
])
def test_normalize_date(raw, expected):
    assert _normalize_date(raw) == expected


def test_normalize_date_invalid():
    assert _normalize_date("어제") is None
    assert _normalize_date("2026-13-40") is None


@pytest.mark.parametrize("raw,expected", [
    ("매우 급함", "상"),
    ("긴급", "상"),
    ("보통", "중"),
    ("낮음", "하"),
])
def test_map_code_value(raw, expected):
    assert _map_code_value(raw, ["상", "중", "하"]) == expected


def test_map_code_value_unmappable():
    assert _map_code_value("ZZZ", ["상", "중", "하"]) is None


# ---------- Self-Correction 루프 ----------

@pytest.fixture(scope="module")
def loaded():
    return ex.load_excel_files(generate_samples()["excels"])


@pytest.fixture
def rules():
    return ValidationRule(
        required_columns=["부서명", "담당자", "요청시스템", "긴급도"],
        date_columns=["요청일자"],
        code_rules={"긴급도": ["상", "중", "하"]},
        duplicate_keys=["부서명", "요청시스템", "개선요청내용"],
    )


def test_self_correction_reduces_errors(loaded, rules):
    # use_llm=False: 결정론 경로를 고정해 오프라인·재현 가능하게 검증
    result = ex.validate_excel_data(loaded, rules)
    sc, corrected, log = run_self_correction(loaded, result, rules, use_llm=False)
    assert sc.accepted
    assert sc.errors_after < sc.errors_before
    assert sc.applied_corrections == 2  # 날짜 + 코드값 (품질팀 4행)
    assert sc.auto_fix_rate == 1.0


def test_self_correction_preserves_originals(loaded, rules):
    """원본 DataFrame 은 변경되지 않아야 한다(원본 보존)."""
    before = loaded[2].df.at[2, "긴급도"]  # 품질팀 데이터 3행(idx 2)
    result = ex.validate_excel_data(loaded, rules)
    run_self_correction(loaded, result, rules, use_llm=False)
    after = loaded[2].df.at[2, "긴급도"]
    assert before == after == "매우 급함"


# ---------- Tree of Thoughts ----------

def test_tot_generates_three_candidates():
    req = ExtractedRequirements(required_fields=["부서명", "담당자", "긴급도"])
    cands = generate_candidates(req, "부서명, 담당자는 필수 입력 항목입니다.")
    assert len(cands) == 3
    assert {c.name for c in cands} == {"A.Strict", "B.Balanced", "C.Loose"}


def test_tot_avoids_overfitting_on_schema_drift():
    """드리프트(요청사유 없음) 시 Strict 보다 점수 낮지 않은 후보 선택."""
    fields = ["부서명", "담당자", "요청시스템", "긴급도", "요청사유"]
    req = ExtractedRequirements(required_fields=fields)
    actual = {"부서명", "담당자", "요청시스템", "긴급도"}  # 요청사유 누락
    rule, log = select_rules_with_tot(
        req, "부서명, 담당자, 요청시스템, 긴급도는 필수 입력 항목입니다.", actual
    )
    # 선택된 규칙은 존재하지 않는 '요청사유'를 필수로 요구하지 않아야 함
    assert "요청사유" not in rule.required_columns
    assert any("SELECT" in line for line in log)


# ---------- 통합 ----------

def test_full_pipeline_runs():
    from smart_collect.pipeline import run_collection
    from smart_collect.sample_data import MOCK_EMAIL

    paths = generate_samples()["excels"]
    state = run_collection("TEST-001", MOCK_EMAIL["subject"], MOCK_EMAIL["body"],
                           paths, prefer_llm=False)
    assert state.current_stage == "completed"
    assert state.validation_result is not None
    assert state.self_correction is not None
    assert state.merged_file is not None
    assert len(state.reasoning_log) >= 5  # PLAN/ToT/VALIDATE/Self-Correction
