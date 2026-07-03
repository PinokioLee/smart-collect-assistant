"""취합 워크플로우 노드 함수 + 선형 오케스트레이터 (Phase 1).

각 함수는 AgentState 를 받아 갱신해 반환하는 '노드' 단위로 작성한다.
Phase 2 의 LangGraph(graph.py)는 이 노드 함수들을 그대로 재사용한다.
"""

from __future__ import annotations

from pathlib import Path

from .config import ERROR_DIR, MERGED_DIR, ensure_dirs
from .observability import trace_execution
from .state import AgentState
from .tools import excel_tools as ex
from .tools.report_tools import generate_result_summary
from .tools.requirement_tools import (
    analyze_collection_email,
    build_validation_rules,
)
from .tools.self_correction import run_self_correction
from .tools.tot_rules import select_rules_with_tot


def node_requirement_analysis(state: AgentState, *, prefer_llm: bool = True) -> AgentState:
    """Requirement Analysis Agent: 메일 → 작성 항목/마감일/주의사항."""
    state.handoff("Requirement Analysis Agent", "RequirementAnalysisNode")
    req = analyze_collection_email(
        state.raw_email_subject or "",
        state.raw_email_body or "",
        prefer_llm=prefer_llm,
    )
    state.extracted_requirements = req
    from .config import settings as _settings

    used_llm = prefer_llm and _settings.azure_ready
    state.step(
        "ANALYZE",
        f"메일에서 작성항목 {len(req.required_fields)}개·마감 '{req.deadline or '미확인'}' 추출",
        actor="llm" if used_llm else "rule",
        detail={"fields": req.required_fields, "deadline": req.deadline},
    )
    trace_execution(
        state.request_id,
        "RequirementAnalysisNode",
        input_summary={"subject": state.raw_email_subject},
        output_summary={"fields": req.required_fields, "deadline": req.deadline},
    )
    return state


def node_supervisor_plan(state: AgentState, *, use_llm: bool = True) -> AgentState:
    """Supervisor Agent: LLM 실행 계획(판단) + ToT 검증 규칙 선택(결정론) + RAG 분기."""
    state.handoff("Supervisor Agent", "PlanningNode")
    req = state.extracted_requirements
    if req is None:
        state.error_state = {"node": "PlanningNode", "message": "요구사항 분석 결과 없음"}
        return state

    # Foresight: 실행 전 5단계 계획을 명시 (고수준 추론 로그)
    state.reason(
        "[PLAN] 5단계 계획 — 1)규칙선택(ToT) 2)검증 3)자가교정(Self-Refine) "
        "4)정상병합 5)보고서. 마감일/필수컬럼/코드값 기준 사전 점검."
    )
    state.step("PLAN", "5단계 실행 계획 수립 (규칙선택→검증→자가교정→병합→보고)")

    # 실제 업로드 엑셀 헤더를 읽는다 (LLM 계획 + ToT 평가 공통 입력)
    actual_columns: set[str] = set()
    try:
        loaded = ex.load_excel_files(state.uploaded_excel_files)
        state._loaded_files = loaded
        for f in loaded:
            actual_columns.update(f.df.columns)
    except Exception:  # noqa: BLE001 - 파일 없으면 ToT 없이 휴리스틱
        pass

    # LLM Supervisor 판단: 검증 전략·리스크를 '계획'(검증은 코드가 결정론적으로 수행)
    plan = None
    if use_llm:
        try:
            from .llm import plan_collection

            plan = plan_collection(req, sorted(actual_columns))
        except Exception:  # noqa: BLE001 - 폴백 보장
            plan = None
    if plan:
        state.supervisor_plan = plan
        risks = "; ".join(plan.get("risks", [])) or "특이 리스크 없음"
        state.reason(
            f"[PLAN·LLM] 전략={plan.get('strategy')} · 리스크: {risks} · "
            f"근거: {plan.get('rationale', '')}"
        )
        state.step(
            "PLAN",
            f"LLM 검증 전략 판단: {plan.get('strategy')} — {plan.get('rationale', '')}",
            actor="llm",
            detail={
                "strategy": plan.get("strategy"),
                "risks": plan.get("risks", []),
                "drift_columns": plan.get("drift_columns", []),
            },
        )
    else:
        state.supervisor_plan = {"strategy": "balanced", "source": "heuristic"}
        state.step("PLAN", "Azure 미사용 → 휴리스틱 계획으로 진행", actor="rule")

    # ToT: 실제 업로드 엑셀 헤더로 후보 규칙 3개를 정합성 점수로 평가·선택 (결정론)
    if actual_columns:
        rule, tot_log = select_rules_with_tot(
            req, "\n".join(req.cautions), actual_columns
        )
        state.validation_rules = rule
        for line in tot_log:
            state.reason(line)
        state.step(
            "BRANCH", "ToT 검증 규칙 후보 3개 생성 (Strict/Balanced/Loose)"
        )
        state.step(
            "SELECT",
            f"정합성 게이트로 규칙 확정 · 필수컬럼={rule.required_columns}",
            detail={"required_columns": rule.required_columns},
        )
    else:
        state.validation_rules = build_validation_rules(req)

    state.rag_required = len(req.required_fields) == 0
    trace_execution(
        state.request_id,
        "PlanningNode",
        output_summary={
            "required_columns": state.validation_rules.required_columns,
            "rag_required": state.rag_required,
            "llm_plan": bool(plan),
        },
    )
    return state


def node_rag_reference(state: AgentState) -> AgentState:
    """RAG Reference Agent (선택): 기준 문서 검색. USE_RAG=true 일 때만 의미."""
    state.handoff("RAG Reference Agent", "RagReferenceNode")
    from .tools.rag_tools import retrieve_reference_documents

    req = state.extracted_requirements
    query = " ".join(req.required_fields) if req else state.raw_email_subject or ""
    rag = retrieve_reference_documents(query, top_k=3)
    state.reference_documents = rag["retrieved_docs"]
    trace_execution(
        state.request_id,
        "RagReferenceNode",
        output_summary={"confidence": rag["confidence_score"]},
    )
    return state


def node_excel_validation(state: AgentState) -> AgentState:
    """Excel Validation Agent: 4가지 규칙 검증."""
    state.handoff("Excel Validation Agent", "ExcelValidationNode")
    rules = state.validation_rules
    if rules is None:
        state.error_state = {"node": "ExcelValidationNode", "message": "검증 규칙 없음"}
        return state
    loaded = state._loaded_files or ex.load_excel_files(state.uploaded_excel_files)
    state._loaded_files = loaded  # 병합 단계에서 재사용 (PrivateAttr)
    state.validation_result = ex.validate_excel_data(loaded, rules)
    vr = state.validation_result
    state.reason(
        f"[VALIDATE] 규칙기반 4종 검증 — {vr.total_rows}행 중 오류 {vr.error_rows}행 "
        f"({', '.join(vr.error_types) or '오류 없음'}). 결정론적 → 재현성 보장"
    )
    state.step(
        "VALIDATE",
        f"규칙기반 4종 검증 — {vr.total_rows}행 중 오류 {vr.error_rows}행 (결정론)",
        detail={"total_rows": vr.total_rows, "error_rows": vr.error_rows,
                "error_types": vr.error_types},
    )
    trace_execution(
        state.request_id,
        "ExcelValidationNode",
        output_summary={
            "total_rows": vr.total_rows,
            "error_rows": vr.error_rows,
        },
    )
    return state


def node_self_correction(state: AgentState, *, use_llm: bool = True) -> AgentState:
    """Self-Correction Agent: 자동 교정 가능한 오류를 Self-Refine 루프로 처리.

    use_llm=True 이고 Azure 준비됨이면 LLM 이 교정값을 제안하고 코드가 검증한다.
    """
    state.handoff("Self-Correction Agent", "SelfCorrectionNode")
    result = state.validation_result
    rules = state.validation_rules
    loaded = state._loaded_files or ex.load_excel_files(state.uploaded_excel_files)
    if result is None or rules is None or not loaded:
        return state

    sc, corrected_files, log = run_self_correction(loaded, result, rules, use_llm=use_llm)
    state.self_correction = sc
    for line in log:
        state.reason(line)

    # 구조화 스텝: CRITIQUE → PROPOSE → REVISE(검증통과 교정) → RE-VALIDATE
    llm_count = sum(1 for c in sc.corrections if c.source == "llm")
    state.step(
        "CRITIQUE",
        f"교정 가능 후보 {sc.fixable_errors}건 선별 (날짜형식·코드값) · "
        f"필수값누락·중복 제외",
        detail={"fixable": sc.fixable_errors},
    )
    if sc.corrections:
        state.step(
            "PROPOSE·VERIFY",
            f"교정 {sc.applied_corrections}건 적용 "
            f"(LLM 제안 {llm_count}건 · 규칙 {sc.applied_corrections - llm_count}건, "
            f"모두 결정론 게이트 통과)",
            actor="llm" if llm_count else "rule",
            detail={
                "applied": sc.applied_corrections,
                "llm": llm_count,
                "corrections": [c.model_dump() for c in sc.corrections],
            },
        )
    state.step(
        "RE-VALIDATE",
        f"재검증 오류 {sc.errors_before}→{sc.errors_after}행 "
        f"({'채택' if sc.accepted else '기각·원본 유지'})",
        detail={"before": sc.errors_before, "after": sc.errors_after,
                "accepted": sc.accepted},
    )

    if sc.accepted:
        # 교정 채택 → 병합/오류보고서는 교정본 + 재검증 결과 기준
        state._loaded_files = corrected_files
        state._post_result = ex.validate_excel_data(corrected_files, rules)
    trace_execution(
        state.request_id,
        "SelfCorrectionNode",
        output_summary={
            "applied": sc.applied_corrections,
            "errors_before": sc.errors_before,
            "errors_after": sc.errors_after,
        },
    )
    return state


def node_merge(state: AgentState) -> AgentState:
    """Excel Merge: 정상 행만 병합 (Self-Correction 채택 시 교정본 기준)."""
    state.handoff("Excel Validation Agent", "ExcelMergeNode")
    # LangGraph 가 state 를 재구성하면 PrivateAttr 가 비므로 필요 시 재로딩
    loaded = state._loaded_files or ex.load_excel_files(state.uploaded_excel_files)
    result = state._post_result or state.validation_result
    if not loaded or result is None:
        state.error_state = {"node": "ExcelMergeNode", "message": "검증 결과 없음"}
        return state
    out = MERGED_DIR / f"{state.request_id}_merged.xlsx"
    path, rows = ex.merge_valid_rows(loaded, result, out, add_metadata=True)
    state.merged_file = path
    state.merged_rows = rows
    state.step("MERGE", f"정상 {rows}행 병합 → 취합 엑셀 생성 (원본 보존)",
               detail={"merged_rows": rows})
    trace_execution(
        state.request_id, "ExcelMergeNode", output_summary={"merged_rows": rows}
    )
    return state


def node_error_report(state: AgentState) -> AgentState:
    """오류 보고서 생성."""
    state.handoff("Excel Validation Agent", "ErrorReportNode")
    # 자가교정 채택 시 잔여 오류 기준으로 보고서 생성
    result = state._post_result or state.validation_result
    if result is None:
        return state
    out = ERROR_DIR / f"{state.request_id}_error_report.xlsx"
    state.error_report = ex.generate_error_report(result, out)
    state.step("REPORT", f"잔여 오류 {len(result.error_details)}건 → 오류 보고서 생성",
               detail={"error_count": len(result.error_details)})
    trace_execution(
        state.request_id,
        "ErrorReportNode",
        output_summary={"error_count": len(result.error_details)},
    )
    return state


def node_report(state: AgentState) -> AgentState:
    """Report Agent: 최종 요약."""
    state.handoff("Report Agent", "ReportNode")
    state.result_summary = generate_result_summary(state)
    state.current_stage = "completed"
    state.step("DONE", "최종 요약 생성 · 세션 완료")
    # 실행 트레이스 증거 파일 저장 (시연·발표용)
    try:
        from .tools.trace_tools import write_execution_trace

        state.trace_files = write_execution_trace(state)
    except Exception:  # noqa: BLE001 - 트레이스 실패는 본 흐름에 영향 없음
        pass
    trace_execution(state.request_id, "ReportNode", output_summary={"status": "completed"})
    return state


def run_collection(
    request_id: str,
    subject: str,
    body: str,
    excel_files: list[str],
    *,
    prefer_llm: bool = True,
) -> AgentState:
    """Phase 1 선형 오케스트레이터 (Supervisor 흐름을 코드로 표현)."""
    ensure_dirs()
    state = AgentState(
        request_id=request_id,
        raw_email_subject=subject,
        raw_email_body=body,
        uploaded_excel_files=[str(Path(p)) for p in excel_files],
    )
    state.handoff("Supervisor Agent", "StartNode")
    trace_execution(request_id, "StartNode", input_summary={"files": len(excel_files)})

    state = node_requirement_analysis(state, prefer_llm=prefer_llm)
    state = node_supervisor_plan(state, use_llm=prefer_llm)
    state = node_excel_validation(state)
    state = node_self_correction(state, use_llm=prefer_llm)
    state = node_merge(state)
    state = node_error_report(state)
    state = node_report(state)
    return state
