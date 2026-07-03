"""Self-Correction 루프 (Self-Refine; Madaan et al., 2023).

문제: 단순 검증은 오류를 '검출'만 한다. 그러나 날짜 형식(2026/06/05)이나
코드값 표기 흔들림(매우 급함→상)처럼 **교정 가능한 오류**는 작성자에게
재제출을 요구하지 않고 시스템이 안전하게 바로잡을 수 있다.

에이전틱 설계 (LLM 제안 → 결정론 검증)
- CRITIQUE : 현재 오류를 분류해 '자동 교정 가능' 후보만 추린다.
- PROPOSE  : LLM(Azure)이 각 오류의 교정값을 '제안'한다(근거 포함).
             Azure 불가/무응답 시 결정론 키워드·날짜 정규화로 폴백한다.
- VERIFY   : 제안값을 결정론 게이트로 검증한다 — 코드값은 allowed 목록에,
             날짜는 실제 YYYY-MM-DD 로 파싱되어야만 통과(환각 차단).
- REVISE   : 검증 통과 제안만 원본 복사본에 적용한다(원본 불변).
- RE-VALIDATE & ACCEPT: 재검증해 **오류 수가 줄었을 때만** 교정을 채택한다.
- 필수값 누락·중복은 데이터를 지어내야 하므로 절대 교정하지 않는다(정직성).

즉, LLM 은 자연어 값의 의미를 '판단'하고, 코드가 '검증·확정'한다. 검증의
재현성(같은 입력 → 같은 채택 결과)은 결정론 게이트가 보장한다.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime

from ..config import settings
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


def _is_valid_iso_date(value: str) -> bool:
    """제안값이 실제 YYYY-MM-DD 날짜인지 결정론적으로 검증."""
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
        return True
    except (ValueError, AttributeError):
        return False


def _verify_proposal(error_type: str, suggested: str, allowed: list[str]) -> bool:
    """LLM/규칙 제안값을 결정론 게이트로 검증한다(환각 차단).

    - 코드값: allowed 목록에 정확히 포함되어야 통과.
    - 날짜  : 실제 YYYY-MM-DD 로 파싱되어야 통과.
    """
    if not suggested:
        return False
    if error_type == "허용되지 않은 코드값":
        return suggested in allowed
    if error_type == "날짜 형식 오류":
        return _is_valid_iso_date(suggested)
    return False


def run_self_correction(
    files: list[LoadedFile],
    result: ExcelValidationResult,
    rules: ValidationRule,
    *,
    use_llm: bool = True,
) -> tuple[SelfCorrectionResult, list[LoadedFile], list[str]]:
    """Self-Refine 루프 실행 (LLM 제안 → 결정론 검증).

    use_llm=True 이고 Azure 준비됨이면 LLM 이 교정값을 제안하고, 코드가 검증한다.
    그 외에는 결정론 키워드·날짜 정규화로 폴백한다. 어느 경로든 채택 게이트
    (재검증 후 오류 감소)는 동일하게 결정론적이므로 재현성이 보장된다.

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

    # 2) PROPOSE — LLM 이 교정값 제안(가능 시). 실패/불가 시 결정론 폴백.
    llm_proposals: dict[int, dict] = {}
    llm_used = False
    if use_llm and settings.azure_ready and fixable:
        payload = [
            {
                "id": i,
                "error_type": e.error_type,
                "column": e.column,
                "value": _original_value(files, e),
                "allowed": rules.code_rules.get(e.column or "", []),
            }
            for i, e in enumerate(fixable)
        ]
        try:
            from ..llm import propose_corrections

            proposed = propose_corrections(payload)
            if proposed is not None:
                llm_proposals = proposed
                llm_used = True
        except Exception:  # noqa: BLE001 - 폴백 보장
            llm_proposals = {}
    log.append(
        f"[Self-Correction] PROPOSE — 교정 제안 주체: "
        f"{'LLM(Azure)' if llm_used else '결정론 규칙(폴백)'}"
    )

    # 3) VERIFY + REVISE — 제안값을 결정론 게이트로 검증 후 원본 복사본에 적용
    corrected_files = copy.deepcopy(files)
    by_name = {f.name: f for f in corrected_files}
    corrections: list[Correction] = []

    for i, e in enumerate(fixable):
        f = by_name.get(e.file)
        if f is None or e.column is None:
            continue
        idx = e.row - HEADER_OFFSET
        if idx < 0 or idx >= len(f.df) or e.column not in f.df.columns:
            continue
        original = str(f.df.at[idx, e.column])
        allowed = rules.code_rules.get(e.column, [])
        method = "날짜정규화" if e.error_type == "날짜 형식 오류" else "코드값매핑"

        # 후보값 결정: LLM 제안 우선, 없으면 결정론 폴백
        proposal = llm_proposals.get(i)
        source = "rule"
        rationale = None
        candidate: str | None = None
        if proposal and proposal.get("suggested"):
            candidate = proposal["suggested"].strip()
            source = "llm"
            rationale = proposal.get("rationale") or None
        else:
            if e.error_type == "날짜 형식 오류":
                candidate = _normalize_date(original)
            else:
                candidate = _map_code_value(original, allowed)

        # VERIFY — 결정론 게이트(허용값/날짜형식) 통과해야만 채택
        verified = bool(
            candidate
            and candidate != original
            and _verify_proposal(e.error_type, candidate, allowed)
        )
        # LLM 제안이 게이트를 통과 못하면 결정론 폴백으로 1회 재시도
        if source == "llm" and not verified:
            fallback = (
                _normalize_date(original)
                if e.error_type == "날짜 형식 오류"
                else _map_code_value(original, allowed)
            )
            if fallback and _verify_proposal(e.error_type, fallback, allowed):
                candidate, source, rationale, verified = fallback, "rule", None, True
                log.append(
                    f"[Self-Correction] VERIFY — {e.file} {e.row}행/{e.column}: "
                    f"LLM 제안 게이트 미통과 → 결정론 폴백 채택"
                )

        if verified and candidate:
            f.df.at[idx, e.column] = candidate
            corrections.append(
                Correction(
                    file=e.file, row=e.row, column=e.column,
                    error_type=e.error_type, before=original, after=candidate,
                    method=method, source=source, rationale=rationale, verified=True,
                )
            )
            tag = "LLM제안" if source == "llm" else "규칙"
            log.append(
                f"[Self-Correction] REVISE — {e.file} {e.row}행/{e.column}: "
                f"'{original}' → '{candidate}' ({method}·{tag}"
                f"{'·' + rationale if rationale else ''})"
            )

    # 4) RE-VALIDATE & ACCEPT — 오류가 줄었을 때만 채택
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


def _original_value(files: list[LoadedFile], e) -> str:
    """오류 셀의 원본 문자열 값을 조회(LLM 제안 입력용)."""
    for f in files:
        if f.name == e.file and e.column in f.df.columns:
            idx = e.row - HEADER_OFFSET
            if 0 <= idx < len(f.df):
                return str(f.df.at[idx, e.column])
    return str(e.value or "")
