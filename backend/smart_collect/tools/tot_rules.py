"""Tree of Thoughts 기반 검증 규칙 선택 (Yao et al., 2023).

문제: 메일에서 추출한 '작성 항목'만으로 검증 규칙을 1개로 확정하면, 작성자마다
양식이 조금씩 달라 실제 제출 엑셀의 컬럼과 어긋날 수 있다(필수 컬럼 과잉/누락).

접근: 단일 규칙 생성 대신 **서로 다른 엄격도의 후보 규칙 3개를 생성(Branch)**하고,
실제 업로드된 엑셀 헤더와의 정합성을 **결정론적 게이트로 평가(Evaluate)**한 뒤
최고 점수 후보를 선택(Select)한다. 비결정성을 제거하고 데이터 정합성을 보장한다.

  BRANCH ×3  →  EVALUATE(coverage gate)  →  SELECT(best)
"""

from __future__ import annotations

from dataclasses import dataclass

from ..state import ExtractedRequirements, ValidationRule
from .requirement_tools import (
    _DATE_HINTS,
    _DEFAULT_CODE_RULES,
    _DEFAULT_DUP_KEYS,
    _DEFAULT_REQUIRED,
    _extract_required,
)


@dataclass
class RuleCandidate:
    name: str
    rule: ValidationRule
    score: float = 0.0
    coverage: float = 0.0
    penalty: float = 0.0


def _date_cols(fields: list[str]) -> list[str]:
    return [f for f in fields if any(h in f.lower() for h in _DATE_HINTS)]


def _code_rules(fields: list[str]) -> dict[str, list[str]]:
    return {c: a for c, a in _DEFAULT_CODE_RULES.items() if c in fields}


def _dup_keys(fields: list[str]) -> list[str]:
    return [k for k in _DEFAULT_DUP_KEYS if k in fields]


def generate_candidates(
    req: ExtractedRequirements, cautions_text: str
) -> list[RuleCandidate]:
    """엄격도가 다른 검증 규칙 후보 3개를 생성한다 (ToT Branch)."""
    fields = req.required_fields or []

    # A. Strict: 모든 작성 항목을 필수로
    strict = ValidationRule(
        required_columns=list(fields),
        date_columns=_date_cols(fields),
        code_rules=_code_rules(fields),
        duplicate_keys=_dup_keys(fields),
    )
    # B. Balanced: 메일의 '필수 입력' 문장에서 도출한 필수 컬럼
    balanced_required = _extract_required(cautions_text, fields)
    balanced = ValidationRule(
        required_columns=balanced_required,
        date_columns=_date_cols(fields),
        code_rules=_code_rules(fields),
        duplicate_keys=_dup_keys(fields),
    )
    # C. Loose: 기본 핵심 필수 컬럼만
    loose_required = [c for c in _DEFAULT_REQUIRED if c in fields] or fields[:1]
    loose = ValidationRule(
        required_columns=loose_required,
        date_columns=_date_cols(fields),
        code_rules=_code_rules(fields),
        duplicate_keys=_dup_keys(fields),
    )
    return [
        RuleCandidate("A.Strict", strict),
        RuleCandidate("B.Balanced", balanced),
        RuleCandidate("C.Loose", loose),
    ]


def evaluate_candidate(cand: RuleCandidate, actual_columns: set[str]) -> RuleCandidate:
    """결정론적 게이트: 실제 엑셀 헤더와의 정합성으로 후보를 채점한다.

    - coverage: 필수/날짜/코드/중복키 컬럼 중 실제 데이터에 존재하는 비율 (↑좋음)
    - penalty : 실제 데이터에 없는 컬럼을 요구하는 비율 (↓좋음, 오탐 유발)
    - score = coverage - 0.5 * penalty
    """
    referenced = (
        list(cand.rule.required_columns)
        + list(cand.rule.date_columns)
        + list(cand.rule.code_rules.keys())
        + list(cand.rule.duplicate_keys)
    )
    referenced = list(dict.fromkeys(referenced))  # 중복 제거, 순서 유지
    if not referenced:
        cand.score = 0.0
        return cand

    present = [c for c in referenced if c in actual_columns]
    absent = [c for c in referenced if c not in actual_columns]
    cand.coverage = len(present) / len(referenced)
    cand.penalty = len(absent) / len(referenced)
    cand.score = round(cand.coverage - 0.5 * cand.penalty, 3)
    return cand


def select_rules_with_tot(
    req: ExtractedRequirements, cautions_text: str, actual_columns: set[str]
) -> tuple[ValidationRule, list[str]]:
    """ToT 로 검증 규칙을 선택하고 고수준 추론 로그를 함께 반환한다.

    Returns: (선택된 ValidationRule, reasoning_log 라인들)
    """
    candidates = generate_candidates(req, cautions_text)
    log: list[str] = []
    log.append(
        f"[ToT] BRANCH ×{len(candidates)} — 검증 규칙 후보 생성 "
        f"({', '.join(c.name for c in candidates)})"
    )
    for c in candidates:
        evaluate_candidate(c, actual_columns)
    scores = " ".join(f"{c.name}={c.score}" for c in candidates)
    log.append(f"[ToT] EVALUATE — coverage 게이트 채점: {scores}")

    best = max(candidates, key=lambda c: (c.score, len(c.rule.required_columns)))
    log.append(
        f"[ToT] SELECT — '{best.name}' 채택 "
        f"(coverage={best.coverage:.2f}, penalty={best.penalty:.2f}, "
        f"필수컬럼={best.rule.required_columns})"
    )
    return best.rule, log
