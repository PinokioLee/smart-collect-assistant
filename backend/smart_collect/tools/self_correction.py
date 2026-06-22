"""Self-Correction 루프 (Self-Refine; Madaan et al., 2023).

문제: 단순 검증은 오류를 '검출'만 한다. 그러나 날짜 형식(2026/06/05)이나
코드값 표기 흔들림(매우 급함→상)처럼 **결정론적으로 교정 가능한 오류**는
작성자에게 재제출을 요구하지 않고 시스템이 안전하게 바로잡을 수 있다.

설계 원칙 (안전한 Self-Refine)
- CRITIQUE: 현재 오류를 분류해 '자동 교정 가능' 후보만 추린다.
- REVISE : 후보를 원본 복사본에 적용한다(원본 불변).
- RE-VALIDATE & ACCEPT: 재검증해 **오류 수가 줄었을 때만** 교정을 채택한다.
  (점수가 오를 때만 채택 — 환각/과잉수정 방지)
- 필수값 누락·중복은 데이터를 지어내야 하므로 자동 교정하지 않는다(정직성).
"""

from __future__ import annotations

import copy
import re
from datetime import datetime

from ..state import (
    Correction,
    ExcelValidationResult,
    SelfCorrectionResult,
    ValidationRule,
)
from .excel_tools import HEADER_OFFSET, LoadedFile, validate_excel_data

# 코드값 표기 흔들림 → 표준값 매핑 (결정론적 휴리스틱)
_CODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "상": ("급", "긴급", "높", "urgent", "critical", "즉시", "심각", "최우선"),
    "중": ("보통", "중간", "일반", "medium", "normal"),
    "하": ("낮", "여유", "low", "사소", "경미"),
}

_DATE_INPUT_FORMATS = ("%Y/%m/%d", "%Y.%m.%d", "%Y년%m월%d일", "%m/%d/%Y", "%Y%m%d")


def _normalize_date(value: str) -> str | None:
    """다양한 날짜 표기를 YYYY-MM-DD 로 정규화. 불가하면 None."""
    text = value.strip().replace(" ", "")
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # 구분자만 다른 경우 숫자 추출로 재시도
    m = re.match(r"^(\d{4})\D(\d{1,2})\D(\d{1,2})$", text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _map_code_value(value: str, allowed: list[str]) -> str | None:
    """허용값 외 코드를 표준 허용값으로 매핑. 불가하면 None."""
    text = value.strip()
    if text in allowed:
        return None
    for canonical, keywords in _CODE_KEYWORDS.items():
        if canonical not in allowed:
            continue
        if any(k in text for k in keywords):
            return canonical
    return None


def run_self_correction(
    files: list[LoadedFile],
    result: ExcelValidationResult,
    rules: ValidationRule,
) -> tuple[SelfCorrectionResult, list[LoadedFile], list[str]]:
    """Self-Refine 루프 실행.

    Returns: (SelfCorrectionResult, 교정 적용된 파일 목록, reasoning_log)
    """
    log: list[str] = []
    errors_before = result.error_rows

    # 1) CRITIQUE — 자동 교정 가능한 오류만 추린다
    fixable = [
        e
        for e in result.error_details
        if e.error_type in ("날짜 형식 오류", "허용되지 않은 코드값")
    ]
    log.append(
        f"[Self-Correction] CRITIQUE — 오류 {errors_before}건 중 "
        f"자동 교정 후보 {len(fixable)}건 (날짜형식/코드값), "
        f"필수값누락·중복은 데이터 생성 불가로 제외"
    )

    # 2) REVISE — 원본 복사본에 교정 적용
    corrected_files = copy.deepcopy(files)
    by_name = {f.name: f for f in corrected_files}
    corrections: list[Correction] = []

    for e in fixable:
        f = by_name.get(e.file)
        if f is None or e.column is None:
            continue
        idx = e.row - HEADER_OFFSET
        if idx < 0 or idx >= len(f.df) or e.column not in f.df.columns:
            continue
        original = str(f.df.at[idx, e.column])

        if e.error_type == "날짜 형식 오류":
            fixed = _normalize_date(original)
            method = "날짜정규화"
        else:  # 허용되지 않은 코드값
            fixed = _map_code_value(original, rules.code_rules.get(e.column, []))
            method = "코드값매핑"

        if fixed and fixed != original:
            f.df.at[idx, e.column] = fixed
            corrections.append(
                Correction(
                    file=e.file,
                    row=e.row,
                    column=e.column,
                    error_type=e.error_type,
                    before=original,
                    after=fixed,
                    method=method,
                )
            )
            log.append(
                f"[Self-Correction] REVISE — {e.file} {e.row}행/{e.column}: "
                f"'{original}' → '{fixed}' ({method})"
            )

    # 3) RE-VALIDATE & ACCEPT — 오류가 줄었을 때만 채택
    revalidated = validate_excel_data(corrected_files, rules)
    errors_after = revalidated.error_rows
    accepted = errors_after < errors_before

    log.append(
        f"[Self-Correction] RE-VALIDATE — 오류 {errors_before} → {errors_after}행 "
        f"({'채택 (개선됨)' if accepted else '기각 (개선 없음, 원본 유지)'})"
    )

    fixable_count = len(fixable)
    sc = SelfCorrectionResult(
        fixable_errors=fixable_count,
        applied_corrections=len(corrections),
        errors_before=errors_before,
        errors_after=errors_after if accepted else errors_before,
        accepted=accepted,
        auto_fix_rate=round(len(corrections) / fixable_count, 3) if fixable_count else 0.0,
        corrections=corrections,
    )

    if accepted:
        return sc, corrected_files, log
    return sc, files, log  # 기각 시 원본 유지
