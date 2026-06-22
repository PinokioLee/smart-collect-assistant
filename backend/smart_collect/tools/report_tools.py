"""Report Agent 도구 - 검증/병합 결과 요약 생성."""

from __future__ import annotations

from collections import Counter

from ..state import AgentState


def generate_result_summary(state: AgentState) -> str:
    """설계서 '최종 응답' 구조에 맞춘 사람이 읽는 요약 텍스트를 생성한다."""
    req = state.extracted_requirements
    res = state.validation_result

    lines: list[str] = []
    lines.append("=" * 56)
    lines.append("  Smart Collect - 엑셀 취합 검증 결과")
    lines.append("=" * 56)

    # 1. 요약 (검출 → 자가교정 → 최종 흐름)
    sc = state.self_correction
    if res:
        lines.append(f"\n[요약] 파일 {res.total_files}개 / 전체 {res.total_rows}행")
        lines.append(f"  · 검증 검출: 오류 {res.error_rows}행")
        if sc and sc.accepted:
            recovered = sc.errors_before - sc.errors_after
            lines.append(
                f"  · 자가교정: {recovered}행 복구 (자동교정 {sc.applied_corrections}건, "
                f"교정율 {sc.auto_fix_rate * 100:.0f}%)"
            )
            lines.append(
                f"  · 최종: 정상 병합 {state.merged_rows}행 / "
                f"재제출 필요 {sc.errors_after}행"
            )
        else:
            lines.append(
                f"  · 최종: 정상 병합 {state.merged_rows or res.valid_rows}행 / "
                f"재제출 필요 {res.error_rows}행"
            )

    # 2. 메일 분석 결과
    if req:
        lines.append("\n[메일 분석 결과]")
        lines.append(f"  - 요청 제목: {req.request_title or '-'}")
        lines.append(f"  - 제출 기한: {req.deadline or '확인 필요'}")
        lines.append(f"  - 작성 항목: {', '.join(req.required_fields) or '-'}")
        if req.cautions:
            lines.append(f"  - 주의 사항: {len(req.cautions)}건")
        if req.missing_info:
            lines.append(f"  - 확인 필요: {', '.join(req.missing_info)}")

    # 3. 엑셀 검증 결과
    if res:
        lines.append("\n[엑셀 검증 결과]")
        if res.error_details:
            type_counts = Counter(e.error_type for e in res.error_details)
            for etype, cnt in type_counts.items():
                lines.append(f"  - {etype}: {cnt}건")
            lines.append("\n  [오류 상세]")
            for e in res.error_details:
                col = f"/{e.column}" if e.column else ""
                val = f" (입력값: {e.value})" if e.value else ""
                lines.append(
                    f"   · {e.file} {e.row}행{col} - {e.error_type}{val}"
                )
        else:
            lines.append("  - 오류 없음 ✅")

    # 3.5 Self-Correction 결과
    sc = state.self_correction
    if sc:
        lines.append("\n[Self-Correction (Self-Refine)]")
        if sc.accepted:
            lines.append(
                f"  - 자동 교정 {sc.applied_corrections}건 적용 → "
                f"오류 {sc.errors_before}행 → {sc.errors_after}행 (채택)"
            )
            lines.append(
                f"  - 자동 교정율: {sc.auto_fix_rate * 100:.0f}% "
                f"(교정가능 {sc.fixable_errors}건 중 {sc.applied_corrections}건)"
            )
            for c in sc.corrections:
                lines.append(
                    f"   · {c.file} {c.row}행/{c.column}: "
                    f"'{c.before}' → '{c.after}' ({c.method})"
                )
        else:
            lines.append("  - 자동 교정 가능한 오류 없음 (필수값 누락/중복은 재제출 필요)")

    # 4. 생성 파일
    lines.append("\n[생성 파일]")
    lines.append(f"  - 병합 파일: {state.merged_file or '-'}")
    lines.append(f"  - 오류 보고서: {state.error_report or '-'}")

    # 5. 확인 필요 사항 / 다음 조치
    remaining = sc.errors_after if (sc and sc.accepted) else (res.error_rows if res else 0)
    if remaining:
        lines.append("\n[다음 조치]")
        lines.append(
            f"  - 자동 교정 불가한 잔여 오류 {remaining}행(필수값 누락/중복)에 대해 "
            f"작성자 재제출 여부를 결정하세요."
        )

    # 6. 실행 추적
    lines.append("\n[실행 추적]")
    lines.append(f"  - request_id: {state.request_id}")
    lines.append(
        f"  - 실행 흐름: {' → '.join(state.agent_handoff_history) or '-'}"
    )
    if state.langfuse_trace_id:
        lines.append(f"  - langfuse_trace_id: {state.langfuse_trace_id}")

    # 7. 고수준 추론 로그 (ToT / Self-Correction / Planning)
    if state.reasoning_log:
        lines.append("\n[고수준 추론 로그]")
        for r in state.reasoning_log:
            lines.append(f"  {r}")
    lines.append("=" * 56)

    return "\n".join(lines)
