"""Excel Validation Agent 규칙 검증 테스트 (샘플 데이터 기준 결정론적)."""

import pytest

from smart_collect.sample_data import generate_samples
from smart_collect.sample_data import generate_project_common_samples
from smart_collect.state import ValidationRule
from smart_collect.tools import excel_tools as ex


@pytest.fixture(scope="module")
def loaded_files():
    paths = generate_samples()["excels"]
    return ex.load_excel_files(paths)


@pytest.fixture
def rules():
    return ValidationRule(
        required_columns=["부서명", "담당자", "요청시스템", "긴급도"],
        date_columns=["요청일자"],
        code_rules={"긴급도": ["상", "중", "하"]},
        duplicate_keys=["부서명", "요청시스템", "개선요청내용"],
    )


def test_required_fields_detects_two_blanks(loaded_files, rules):
    errors = ex.validate_required_fields(loaded_files, rules.required_columns)
    # 영업팀 요청시스템 누락 + 생산팀 담당자 누락 = 2
    assert len(errors) == 2
    cols = {(e.file, e.column) for e in errors}
    assert ("개선요청_영업팀.xlsx", "요청시스템") in cols
    assert ("개선요청_생산팀.xlsx", "담당자") in cols


def test_date_format_detects_slash(loaded_files, rules):
    errors = ex.validate_date_format(loaded_files, rules.date_columns)
    assert len(errors) == 1
    assert errors[0].value == "2026/06/05"
    assert errors[0].error_type == "날짜 형식 오류"


def test_code_values_detects_invalid_priority(loaded_files, rules):
    errors = ex.validate_code_values(loaded_files, rules.code_rules)
    assert len(errors) == 1
    assert errors[0].value == "매우 급함"


def test_duplicates_detects_one(loaded_files, rules):
    errors = ex.validate_duplicates(loaded_files, rules.duplicate_keys)
    assert len(errors) == 1
    assert errors[0].error_type == "중복 데이터"
    # 최초 출현이 아닌 두 번째 행이 오류로 기록됨
    assert errors[0].file == "개선요청_생산팀.xlsx"


def test_aggregate_counts(loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    assert result.total_files == 3
    assert result.total_rows == 11
    assert result.error_rows == 4  # 품질팀 4행은 오류 2건이지만 행은 1개
    assert result.valid_rows == 7


def test_merge_excludes_error_rows(tmp_path, loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    out = tmp_path / "merged.xlsx"
    path, rows = ex.merge_valid_rows(loaded_files, result, out)
    assert rows == 7  # 정상 행만
    assert out.exists()


def test_error_report_created(tmp_path, loaded_files, rules):
    result = ex.validate_excel_data(loaded_files, rules)
    out = tmp_path / "errors.xlsx"
    path = ex.generate_error_report(result, out)
    assert out.exists()


def test_missing_column_detected(loaded_files):
    # 존재하지 않는 필수 컬럼 → '필수 컬럼 누락'
    errors = ex.validate_required_fields(loaded_files, ["없는컬럼"])
    assert all(e.error_type == "필수 컬럼 누락" for e in errors)
    assert len(errors) == 3  # 3개 파일 모두


def test_project_common_samples_created():
    result = generate_project_common_samples()
    assert len(result["excels"]) == 5
    assert result["reference"].endswith("프로젝트_기준정보.xlsx")
    assert len(result["targets"]) == 4
    assert "프로젝트번호" in result["common_columns"]


def test_sync_common_fields_from_reference(tmp_path):
    result = generate_project_common_samples()
    reference = result["reference"]
    targets = result["targets"][:1]

    out = ex.sync_common_fields_from_reference(
        reference,
        targets,
        result["common_columns"],
        output_dir=tmp_path,
    )

    assert out["update_count"] > 0
    assert out["reference_file"] == "프로젝트_기준정보.xlsx"
    assert len(out["updated_files"]) == 1
    synced = ex.load_excel_files(out["updated_files"])[0].df
    assert synced.loc[0, "수주금액"] == "150000000"
    assert "청구차수" in synced.columns  # 개별 컬럼 보존
