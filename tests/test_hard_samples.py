"""하드(현실 난이도) 샘플 회귀 테스트 (item 2).

generate_hard_samples() 가 만드는 제출 엑셀은 5종 검증 오류 + 스키마 드리프트 +
통화/콤마 숫자 + 파일 간 중복을 담는다. 검증은 여전히 결정론적이므로,
같은 입력 -> 같은 결과(행 수·오류 수·오류 유형)를 이 테스트로 고정한다.
"""

import pytest

from smart_collect.sample_data import HARD_EXPECTED, generate_hard_samples
from smart_collect.state import ValidationRule
from smart_collect.tools import excel_tools as ex
from smart_collect.tools.self_correction import run_self_correction


@pytest.fixture(scope="module")
def loaded_files():
    paths = generate_hard_samples()["excels"]
    return ex.load_excel_files(paths)


@pytest.fixture
def rules():
    # 하드 메일도 동일한 취합 요청이므로 검증 규칙은 기본 세트와 같다.
    return ValidationRule(
        required_columns=["부서명", "담당자", "요청시스템", "긴급도"],
        date_columns=["요청일자"],
        code_rules={"긴급도": ["상", "중", "하"]},
        duplicate_keys=["부서명", "요청시스템", "개선요청내용"],
    )


def test_hard_samples_written():
    result = generate_hard_samples()
    assert len(result["excels"]) == 3
    assert result["email"].endswith("mock_email.json")
    assert result["expected"] == HARD_EXPECTED


def test_hard_aggregate_counts_are_deterministic(loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    assert result.total_files == HARD_EXPECTED["total_files"]
    assert result.total_rows == HARD_EXPECTED["total_rows"]
    assert result.error_rows == HARD_EXPECTED["error_rows"]
    assert result.valid_rows == HARD_EXPECTED["valid_rows"]


def test_hard_samples_exercise_all_five_error_types(loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    assert sorted(result.error_types) == HARD_EXPECTED["error_types"]
    # 기본 샘플에는 없던 '필수 컬럼 누락'(요청시스템 -> 시스템명 개명)이 포함된다.
    assert "필수 컬럼 누락" in result.error_types


def test_hard_renamed_required_column_flagged(loaded_files, rules):
    errors = ex.validate_required_fields(loaded_files, rules.required_columns)
    missing_cols = {
        (e.file, e.column) for e in errors if e.error_type == "필수 컬럼 누락"
    }
    assert ("개선요청_품질본부.xlsx", "요청시스템") in missing_cols


def test_hard_cross_file_duplicate_detected(loaded_files, rules):
    errors = ex.validate_duplicates(loaded_files, rules.duplicate_keys)
    # 정보시스템팀 공통 요청이 영업본부(최초) -> 생산본부(중복)로 잡힌다.
    assert len(errors) == 1
    dup = errors[0]
    assert dup.error_type == "중복 데이터"
    assert dup.file == "개선요청_생산본부.xlsx"
    assert "개선요청_영업본부.xlsx" in (dup.detail or "")


def test_hard_currency_columns_preserved_as_text(loaded_files):
    # 콤마/통화 표기는 검증하지 않고 원본 문자열 그대로 보존한다.
    영업 = next(f for f in loaded_files if f.name == "개선요청_영업본부.xlsx")
    assert "예상비용" in 영업.df.columns
    assert "1,200,000" in set(영업.df["예상비용"])
    생산 = next(f for f in loaded_files if f.name == "개선요청_생산본부.xlsx")
    assert "₩1,500,000" in set(생산.df["예상비용"])


def test_hard_self_correction_fixes_only_safe_errors(loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    sc, corrected, _log = run_self_correction(
        loaded_files, result, rules, use_llm=False
    )
    # 날짜 점표기 1 + 코드값 '긴급' 1 = 2건만 안전 교정, "미정" 2건은 잔여.
    assert sc.fixable_errors == HARD_EXPECTED["self_correction_fixable"]
    assert sc.applied_corrections == HARD_EXPECTED["self_correction_applied"]
    assert sc.accepted is True
    assert sc.errors_after < sc.errors_before
    methods = {c.method for c in sc.corrections}
    assert methods == {"날짜정규화", "코드값매핑"}


def test_hard_merge_excludes_error_rows(tmp_path, loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    out = tmp_path / "hard_merged.xlsx"
    _path, rows = ex.merge_valid_rows(loaded_files, result, out)
    assert rows == HARD_EXPECTED["valid_rows"]
    assert out.exists()
