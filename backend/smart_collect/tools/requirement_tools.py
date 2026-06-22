"""Requirement Analysis Agent 도구.

취합 요청 메일 -> 작성 항목/마감일/주의사항 추출(analyze_collection_email)
추출 결과 -> 엑셀 검증 규칙 생성(build_validation_rules)

Phase 1: LLM 없이 휴리스틱으로 동작 (재현 가능, 무비용).
Phase 2: settings.azure_ready 이면 Azure OpenAI 로 추출 (llm.py).
"""

from __future__ import annotations

import re

from ..state import ExtractedRequirements, ValidationRule

# 기본 코드값 규칙 (긴급도)
_DEFAULT_CODE_RULES: dict[str, list[str]] = {"긴급도": ["상", "중", "하"]}

# 날짜성 컬럼 판별 키워드
_DATE_HINTS = ("일자", "날짜", "일시", "date")

# 기본 필수 컬럼 후보 (메일에서 명시 못 찾을 때 fallback)
_DEFAULT_REQUIRED = ["부서명", "담당자", "요청시스템", "긴급도"]

# 기본 중복 판정 키 후보
_DEFAULT_DUP_KEYS = ["부서명", "요청시스템", "개선요청내용"]


def _extract_fields(body: str) -> list[str]:
    """'작성 항목은 A, B, C 입니다' 패턴에서 항목 목록을 추출."""
    m = re.search(r"작성\s*항목은\s*(.+?)(?:입니다|입니다\.)", body)
    if not m:
        return []
    chunk = m.group(1)
    parts = re.split(r"[,/·]", chunk)
    return [p.strip() for p in parts if p.strip()]


def _extract_deadline(body: str) -> str | None:
    """'2026년 6월 12일 17시' 같은 마감일을 ISO 풍으로 정규화."""
    m = re.search(
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일(?:\s*(\d{1,2})시)?", body
    )
    if not m:
        return None
    y, mo, d, h = m.groups()
    hh = f"{int(h):02d}:00" if h else "00:00"
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {hh}"


def _extract_required(body: str, fields: list[str]) -> list[str]:
    """'A, B, C 는 필수 입력' 문장에서 필수 컬럼을 추출."""
    m = re.search(r"(.+?)(?:은|는)\s*필수\s*입력", body)
    if m:
        cand = re.split(r"[,/·]", m.group(1))
        required = [c.strip() for c in cand if c.strip() in fields]
        if required:
            return required
    # fallback: 기본 후보 중 fields 에 있는 것
    return [c for c in _DEFAULT_REQUIRED if c in fields] or fields


def _extract_cautions(body: str) -> list[str]:
    cautions: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if any(k in line for k in ("긴급도", "형식", "필수")):
            cautions.append(line)
    return cautions


def analyze_collection_email_heuristic(
    subject: str, body: str
) -> ExtractedRequirements:
    """LLM 없이 규칙 기반으로 메일을 분석한다."""
    fields = _extract_fields(body)
    deadline = _extract_deadline(body)
    missing: list[str] = []
    if not fields:
        missing.append("작성 항목")
    if not deadline:
        missing.append("제출 기한")
    return ExtractedRequirements(
        request_title=subject.strip() or None,
        purpose=subject.strip() or None,
        deadline=deadline,
        required_fields=fields,
        cautions=_extract_cautions(body),
        missing_info=missing,
    )


def analyze_collection_email(
    subject: str, body: str, *, prefer_llm: bool = True
) -> ExtractedRequirements:
    """메일 분석. Azure 키가 있고 prefer_llm 이면 LLM, 아니면 휴리스틱.

    LLM 경로 실패 시 자동으로 휴리스틱으로 폴백한다.
    """
    if prefer_llm:
        try:
            from ..llm import analyze_email_with_llm  # 지연 임포트

            llm_result = analyze_email_with_llm(subject, body)
            if llm_result is not None:
                return llm_result
        except Exception:  # noqa: BLE001 - 폴백 보장
            pass
    return analyze_collection_email_heuristic(subject, body)


def build_validation_rules(req: ExtractedRequirements) -> ValidationRule:
    """추출된 작성 항목을 기반으로 엑셀 검증 규칙을 구성한다."""
    fields = req.required_fields or []

    date_columns = [
        f for f in fields if any(h in f.lower() for h in _DATE_HINTS)
    ]
    code_rules = {
        col: allowed for col, allowed in _DEFAULT_CODE_RULES.items() if col in fields
    }
    duplicate_keys = [k for k in _DEFAULT_DUP_KEYS if k in fields]
    required_columns = _extract_required(_safe_body(req), fields)

    return ValidationRule(
        required_columns=required_columns,
        date_columns=date_columns,
        code_rules=code_rules,
        duplicate_keys=duplicate_keys,
    )


def _safe_body(req: ExtractedRequirements) -> str:
    """필수 컬럼 재추출용 텍스트 (cautions 결합)."""
    return "\n".join(req.cautions)
