"""LangGraph Multi-Agent Supervisor 그래프 (Phase 2).

설계서 'LangGraph Node / Edge 흐름' 을 코드로 구현한다.
노드 로직은 pipeline.py 의 노드 함수를 재사용하고, 여기서는 그래프 구성과
Supervisor 의 조건 분기(라우팅)만 담당한다.

  START → Requirement Analysis → Supervisor(Planning)
        → [조건분기] RAG 필요? → RAG Reference → Excel Validation
                              아니오        → Excel Validation
        → Excel Merge → Error Report → Report → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import settings
from .pipeline import (
    node_error_report,
    node_excel_validation,
    node_merge,
    node_rag_reference,
    node_report,
    node_requirement_analysis,
    node_self_correction,
    node_supervisor_plan,
)
from .state import AgentState


def _requirement_node(state: AgentState) -> AgentState:
    return node_requirement_analysis(state, prefer_llm=True)


def route_after_planning(state: AgentState) -> str:
    """Supervisor 라우팅: RAG 필요 여부에 따라 다음 노드 결정."""
    if state.rag_required and settings.use_rag:
        return "rag_reference"
    return "excel_validation"


def build_graph():
    """컴파일된 LangGraph 워크플로우를 반환한다."""
    g = StateGraph(AgentState)

    g.add_node("requirement_analysis", _requirement_node)
    g.add_node("planning", node_supervisor_plan)
    g.add_node("rag_reference", node_rag_reference)
    g.add_node("excel_validation", node_excel_validation)
    g.add_node("self_correction", node_self_correction)
    g.add_node("merge", node_merge)
    g.add_node("error_report", node_error_report)
    g.add_node("report", node_report)

    g.add_edge(START, "requirement_analysis")
    g.add_edge("requirement_analysis", "planning")
    g.add_conditional_edges(
        "planning",
        route_after_planning,
        {"rag_reference": "rag_reference", "excel_validation": "excel_validation"},
    )
    g.add_edge("rag_reference", "excel_validation")
    g.add_edge("excel_validation", "self_correction")
    g.add_edge("self_correction", "merge")
    g.add_edge("merge", "error_report")
    g.add_edge("error_report", "report")
    g.add_edge("report", END)

    return g.compile()


def run_collection_graph(
    request_id: str, subject: str, body: str, excel_files: list[str]
) -> AgentState:
    """LangGraph 워크플로우로 취합 1건을 실행한다."""
    from pathlib import Path

    from .config import ensure_dirs

    ensure_dirs()
    app = build_graph()
    initial = AgentState(
        request_id=request_id,
        raw_email_subject=subject,
        raw_email_body=body,
        uploaded_excel_files=[str(Path(p)) for p in excel_files],
    )
    result = app.invoke(initial)
    # LangGraph 는 dict 또는 AgentState 를 반환할 수 있어 정규화
    if isinstance(result, AgentState):
        return result
    return AgentState.model_validate(result)
