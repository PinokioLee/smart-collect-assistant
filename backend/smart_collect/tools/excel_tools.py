"""Excel Validation Agent 의 규칙 기반 도구 (pandas/openpyxl).

설계 원칙
---------
- 엑셀 검증/병합은 LLM 판단이 아니라 결정론적 규칙 로직으로 처리한다.
- 원본 파일은 절대 수정하지 않는다. 결과는 별도 파일로 생성한다.
- 오류 데이터는 자동 수정하지 않고 오류 보고서에 기록한다.

엑셀 행 번호 규약
-----------------
- 1행 = 헤더. 데이터 첫 행 = 2행.
- pandas DataFrame index 0  ->  엑셀 2행. (excel_row = idx + 2)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..config import DATA_DIR
from ..state import ErrorDetail, ExcelValidationResult, ValidationRule

# 데이터 첫 행의 엑셀 행 번호 (헤더 1행 다음)
HEADER_OFFSET = 2

# 추적용 메타데이터 컬럼명
META_SOURCE_FILE = "_원본파일"
META_SOURCE_ROW = "_원본행"


@dataclass
class LoadedFile:
    """읽어들인 엑셀 파일 1개."""

    path: str
    name: str
    df: pd.DataFrame


def _is_blank(value: object) -> bool:
    """결측/공백 판정."""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def load_excel_files(excel_files: list[str]) -> list[LoadedFile]:
    """업로드된 엑셀 파일들을 DataFrame 으로 읽는다.

    모든 셀을 문자열로 읽어(`dtype=str`) 날짜/코드값을 원본 그대로 검증한다.
    """
    loaded: list[LoadedFile] = []
    for raw in excel_files:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"엑셀 파일을 찾을 수 없습니다: {path}")
        df = pd.read_excel(path, dtype=str, engine="openpyxl")
        # 완전 빈 행 제거 (꼬리 빈 행 방지)
        df = df.dropna(how="all").reset_index(drop=True)
        loaded.append(LoadedFile(path=str(path), name=path.name, df=df))
    return loaded


def validate_required_fields(
    files: list[LoadedFile], required_columns: list[str]
) -> list[ErrorDetail]:
    """필수 컬럼 존재 여부 + 필수값 누락(빈 값)을 검증한다."""
    errors: list[ErrorDetail] = []
    for f in files:
        # 1) 컬럼 자체가 없는 경우
        missing_cols = [c for c in required_columns if c not in f.df.columns]
        for col in missing_cols:
            errors.append(
                ErrorDetail(
                    file=f.name,
                    row=1,
                    column=col,
                    error_type="필수 컬럼 누락",
                    detail=f"'{col}' 컬럼이 양식에 존재하지 않습니다.",
                )
            )
        # 2) 값이 비어있는 경우
        present_cols = [c for c in required_columns if c in f.df.columns]
        for idx, record in f.df.iterrows():
            for col in present_cols:
                if _is_blank(record[col]):
                    errors.append(
                        ErrorDetail(
                            file=f.name,
                            row=int(idx) + HEADER_OFFSET,
                            column=col,
                            error_type="필수값 누락",
                            detail=f"'{col}' 값이 비어 있습니다.",
                        )
                    )
    return errors


_DATE_PATTERNS = ("%Y-%m-%d", "%Y/%m/%d")


def _parse_date(text: str, fmt: str = "%Y-%m-%d") -> bool:
    """기준 포맷으로 파싱 가능한지 확인."""
    try:
        datetime.strptime(text.strip(), fmt)
        return True
    except (ValueError, TypeError):
        return False


def validate_date_format(
    files: list[LoadedFile],
    date_columns: list[str],
    expected_format: str = "%Y-%m-%d",
) -> list[ErrorDetail]:
    """날짜 컬럼이 기대 포맷(기본 YYYY-MM-DD)을 따르는지 검증한다."""
    errors: list[ErrorDetail] = []
    for f in files:
        for col in date_columns:
            if col not in f.df.columns:
                continue
            for idx, value in f.df[col].items():
                if _is_blank(value):
                    continue  # 누락은 required 검증이 담당
                if not _parse_date(str(value), expected_format):
                    errors.append(
                        ErrorDetail(
                            file=f.name,
                            row=int(idx) + HEADER_OFFSET,
                            column=col,
                            error_type="날짜 형식 오류",
                            value=str(value),
                            detail=f"기대 형식 {expected_format} 이 아닙니다.",
                        )
                    )
    return errors


def validate_code_values(
    files: list[LoadedFile], code_rules: dict[str, list[str]]
) -> list[ErrorDetail]:
    """코드값/허용값 목록에 없는 값을 검증한다 (예: 긴급도 = 상/중/하)."""
    errors: list[ErrorDetail] = []
    for f in files:
        for col, allowed in code_rules.items():
            if col not in f.df.columns:
                continue
            allowed_set = {a.strip() for a in allowed}
            for idx, value in f.df[col].items():
                if _is_blank(value):
                    continue
                if str(value).strip() not in allowed_set:
                    errors.append(
                        ErrorDetail(
                            file=f.name,
                            row=int(idx) + HEADER_OFFSET,
                            column=col,
                            error_type="허용되지 않은 코드값",
                            value=str(value),
                            detail=f"허용값: {' / '.join(allowed)}",
                        )
                    )
    return errors


def validate_duplicates(
    files: list[LoadedFile], duplicate_keys: list[str]
) -> list[ErrorDetail]:
    """지정한 키 컬럼 조합으로 중복 행을 검증한다 (파일 경계를 넘어 전체 기준)."""
    if not duplicate_keys:
        return []

    # 키 컬럼이 모든 파일에 존재하는지 확인
    rows: list[tuple[str, int, tuple]] = []  # (file, excel_row, key_tuple)
    for f in files:
        if not all(k in f.df.columns for k in duplicate_keys):
            continue
        for idx, record in f.df.iterrows():
            key = tuple(str(record[k]).strip() for k in duplicate_keys)
            if any(_is_blank(part) for part in key):
                continue  # 키가 비면 중복 판정 제외
            rows.append((f.name, int(idx) + HEADER_OFFSET, key))

    seen: dict[tuple, tuple[str, int]] = {}
    errors: list[ErrorDetail] = []
    for file_name, excel_row, key in rows:
        if key in seen:
            first_file, first_row = seen[key]
            errors.append(
                ErrorDetail(
                    file=file_name,
                    row=excel_row,
                    column=", ".join(duplicate_keys),
                    error_type="중복 데이터",
                    value=" | ".join(key),
                    detail=f"최초 출현: {first_file} {first_row}행",
                )
            )
        else:
            seen[key] = (file_name, excel_row)
    return errors


def validate_excel_data(
    files: list[LoadedFile], rules: ValidationRule
) -> ExcelValidationResult:
    """4가지 규칙 검증을 모두 수행하고 결과를 집계한다."""
    all_errors: list[ErrorDetail] = []
    all_errors += validate_required_fields(files, rules.required_columns)
    all_errors += validate_date_format(files, rules.date_columns)
    all_errors += validate_code_values(files, rules.code_rules)
    all_errors += validate_duplicates(files, rules.duplicate_keys)

    total_rows = sum(len(f.df) for f in files)

    # (파일, 행) 기준으로 오류 행 집계 — 헤더(1행) 오류는 행 단위 집계 제외
    error_row_keys = {
        (e.file, e.row) for e in all_errors if e.row >= HEADER_OFFSET
    }
    error_rows = len(error_row_keys)
    valid_rows = max(total_rows - error_rows, 0)

    error_types = sorted({e.error_type for e in all_errors})

    return ExcelValidationResult(
        total_files=len(files),
        total_rows=total_rows,
        valid_rows=valid_rows,
        error_rows=error_rows,
        error_types=error_types,
        error_details=all_errors,
    )


def merge_valid_rows(
    files: list[LoadedFile],
    result: ExcelValidationResult,
    output_path: str | Path,
    add_metadata: bool = True,
) -> tuple[str, int]:
    """오류 없는 정상 행만 모아 하나의 취합 파일로 병합한다.

    Returns: (병합 파일 경로, 병합된 행 수)
    """
    error_row_keys = {
        (e.file, e.row) for e in result.error_details if e.row >= HEADER_OFFSET
    }

    frames: list[pd.DataFrame] = []
    for f in files:
        keep_mask = [
            (f.name, int(idx) + HEADER_OFFSET) not in error_row_keys
            for idx in f.df.index
        ]
        kept = f.df.loc[keep_mask].copy()
        if add_metadata and not kept.empty:
            kept.insert(0, META_SOURCE_FILE, f.name)
            kept.insert(
                1,
                META_SOURCE_ROW,
                [int(idx) + HEADER_OFFSET for idx in kept.index],
            )
        frames.append(kept)

    merged = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame()
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(output_path, index=False, engine="openpyxl")
    return str(output_path), len(merged)


def update_common_fields(
    excel_files: list[str],
    target_field: str,
    new_value: str,
    *,
    old_value: str | None = None,
    add_if_missing: bool = True,
    output_dir: str | Path | None = None,
) -> dict:
    """여러 엑셀 파일의 공통 항목(컬럼)을 한 번에 일괄 수정한다.

    실무 시나리오: 공통 항목(취합월/마감일/기준 등)이 바뀌면 파일 N개를 모두 열어
    반복 수정해야 하는 문제를, 한 번의 호출로 전체 반영한다.

    - old_value 가 주어지면 그 값과 일치하는 셀만 new_value 로 교체.
    - old_value 가 None 이면 해당 컬럼 전체를 new_value 로 설정.
    - 컬럼이 없고 add_if_missing 이면 컬럼을 추가하고 new_value 로 채움.
    - 원본은 보존하고 결과는 별도 파일(_updated)로 저장한다.

    Returns: {updated_files, update_count, details, error_list}
    """
    files = load_excel_files(excel_files)
    out_base = Path(output_dir) if output_dir else (DATA_DIR / "updated_files")
    out_base.mkdir(parents=True, exist_ok=True)

    updated_files: list[str] = []
    details: list[dict] = []
    error_list: list[dict] = []
    total_updates = 0

    for f in files:
        df = f.df.copy()
        changed = 0
        if target_field not in df.columns:
            if add_if_missing:
                df[target_field] = new_value
                changed = len(df)
            else:
                error_list.append({"file": f.name, "reason": f"'{target_field}' 컬럼 없음"})
                continue
        else:
            col = df[target_field].astype("object")
            if old_value is None:
                changed = int((col.map(lambda v: str(v) != new_value)).sum())
                df[target_field] = new_value
            else:
                mask = col.map(lambda v: str(v).strip() == str(old_value).strip())
                changed = int(mask.sum())
                df.loc[mask, target_field] = new_value

        out_path = out_base / f"{Path(f.name).stem}_updated.xlsx"
        df.to_excel(out_path, index=False, engine="openpyxl")
        updated_files.append(str(out_path))
        details.append({"file": f.name, "updated_cells": changed, "output": str(out_path)})
        total_updates += changed

    return {
        "updated_files": updated_files,
        "update_count": total_updates,
        "details": details,
        "error_list": error_list,
    }


def generate_error_report(
    result: ExcelValidationResult, output_path: str | Path
) -> str:
    """오류 상세를 엑셀 보고서로 생성한다."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if result.error_details:
        rows = [
            {
                "파일명": e.file,
                "행": e.row,
                "컬럼": e.column or "",
                "오류유형": e.error_type,
                "입력값": e.value or "",
                "상세": e.detail or "",
            }
            for e in result.error_details
        ]
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(
            columns=["파일명", "행", "컬럼", "오류유형", "입력값", "상세"]
        )

    df.to_excel(output_path, index=False, engine="openpyxl")
    return str(output_path)
