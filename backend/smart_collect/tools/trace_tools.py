"""실행 트레이스 증거 파일 생성 — 시연 영상·발표 자료용.

취합 1건이 끝나면, 에이전트들이 '어떤 순서로 / 무엇을 / 무엇으로(LLM/규칙) 판단했는지'를
사람이 읽을 수 있는 형태로 남긴다. 시연 영상에서 이 파일을 그대로 보여주고,
발표에서 "추론 과정을 기록·증명한다"는 근거로 인용할 수 있다.

  data/traces/{request_id}.json  — 구조화 원본(재현·검증용)
  data/traces/{request_id}.md    — 사람이 읽는 타임라인(시연 화면용)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..config import DATA_DIR
from ..state import AgentState

TRACE_DIR = DATA_DIR / "traces"

_ACTOR_LABEL = {"llm": "🧠 LLM 판단", "rule": "⚙️ 규칙(결정론)"}


def _build_payload(state: AgentState) -> dict:
    sc = state.self_correction
    vr = state.validation_result
    return {
        "request_id": state.request_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "email_subject": state.raw_email_subject,
        "supervisor_plan": state.supervisor_plan,
        "agent_handoff_history": state.agent_handoff_history,
        "validation": (
            {
                "total_rows": vr.total_rows,
                "error_rows": vr.error_rows,
                "error_types": vr.error_types,
            }
            if vr
            else None
        ),
        "self_correction": (
            {
                "fixable_errors": sc.fixable_errors,
                "applied_corrections": sc.applied_corrections,
                "llm_proposed": sum(1 for c in sc.corrections if c.source == "llm"),
                "errors_before": sc.errors_before,
                "errors_after": sc.errors_after,
                "accepted": sc.accepted,
                "corrections": [c.model_dump() for c in sc.corrections],
            }
            if sc
            else None
        ),
        "reasoning_steps": [s.model_dump() for s in state.reasoning_steps],
        "reasoning_log": state.reasoning_log,
    }


def _render_markdown(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"# 에이전트 실행 트레이스 — {payload['request_id']}")
    lines.append("")
    lines.append(f"- 생성 시각: {payload['generated_at']}")
    lines.append(f"- 요청 메일: {payload.get('email_subject') or '-'}")
    plan = payload.get("supervisor_plan") or {}
    if plan:
        lines.append(
            f"- Supervisor 계획: 전략={plan.get('strategy', '-')}"
            + (f" · 근거: {plan.get('rationale')}" if plan.get("rationale") else "")
        )
        if plan.get("risks"):
            lines.append(f"- 사전 식별 리스크: {'; '.join(plan['risks'])}")
    lines.append("")

    lines.append("## 단계별 추론 타임라인")
    lines.append("")
    lines.append("| # | 에이전트 | 국면 | 판단 주체 | 판단 내용 |")
    lines.append("|---|---------|------|-----------|-----------|")
    for s in payload["reasoning_steps"]:
        actor = _ACTOR_LABEL.get(s["actor"], s["actor"])
        decision = str(s["decision"]).replace("|", "\\|")
        lines.append(
            f"| {s['seq']} | {s['agent']} | {s['phase']} | {actor} | {decision} |"
        )
    lines.append("")

    sc = payload.get("self_correction")
    if sc and sc.get("corrections"):
        lines.append("## 자가교정 상세 (LLM 제안 → 결정론 검증 → 채택)")
        lines.append("")
        lines.append("| 파일 | 행 | 컬럼 | 오류유형 | 원본 → 교정 | 주체 | 근거 |")
        lines.append("|------|----|------|----------|-------------|------|------|")
        for c in sc["corrections"]:
            actor = _ACTOR_LABEL.get(c.get("source", "rule"), c.get("source"))
            rationale = (c.get("rationale") or "-").replace("|", "\\|")
            lines.append(
                f"| {c['file']} | {c['row']} | {c['column']} | {c['error_type']} | "
                f"`{c['before']}` → `{c['after']}` | {actor} | {rationale} |"
            )
        lines.append("")

    lines.append("## 원시 추론 로그")
    lines.append("")
    lines.append("```text")
    for line in payload["reasoning_log"]:
        lines.append(line)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_execution_trace(state: AgentState) -> dict[str, str]:
    """트레이스 JSON + Markdown 을 저장하고 경로 딕셔너리를 반환한다."""
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    payload = _build_payload(state)

    json_path = TRACE_DIR / f"{state.request_id}.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md_path = TRACE_DIR / f"{state.request_id}.md"
    md_path.write_text(_render_markdown(payload), encoding="utf-8")

    return {"json": str(json_path), "md": str(md_path)}
