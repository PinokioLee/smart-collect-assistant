"""Agent State 및 도메인 모델 (설계서 '최소 AgentState' 기준).

Supervisor Agent 가 취합 요청 1건을 하나의 Job(=AgentState)으로 관리한다.
모든 전문 Agent 는 이 State 를 읽고/갱신하며 협업한다.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, PrivateAttr


class ExtractedRequirements(BaseModel):
    """Requirement Analysis Agent 가 메일에서 추출한 요구사항."""

    request_title: Optional[str] = None
    purpose: Optional[str] = None
    deadline: Optional[str] = None
    required_fields: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


class ValidationRule(BaseModel):
    """추출된 작성 항목을 기반으로 생성한 엑셀 검증 규칙."""

    required_columns: list[str] = Field(default_factory=list)
    date_columns: list[str] = Field(default_factory=list)
    # 컬럼명 -> 허용값 목록 (예: {"긴급도": ["상", "중", "하"]})
    code_rules: dict[str, list[str]] = Field(default_factory=dict)
    duplicate_keys: list[str] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    """검증 오류 1건."""

    file: str
    row: int  # 엑셀 기준 행 번호 (헤더=1, 데이터 시작=2)
    column: Optional[str] = None
    error_type: str  # 필수값 누락 / 날짜 형식 오류 / 허용되지 않은 코드값 / 중복 데이터
    value: Optional[str] = None
    detail: Optional[str] = None


class ExcelValidationResult(BaseModel):
    """Excel Validation Agent 의 검증 결과 집계."""

    total_files: int = 0
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    error_types: list[str] = Field(default_factory=list)
    error_details: list[ErrorDetail] = Field(default_factory=list)


class Correction(BaseModel):
    """Self-Correction Agent 가 제안/적용한 자동 교정 1건."""

    file: str
    row: int
    column: str
    error_type: str
    before: str
    after: str
    method: str  # 날짜정규화 / 코드값매핑


class SelfCorrectionResult(BaseModel):
    """Self-Refine 루프 결과 (생성→비평→수정→재검증)."""

    fixable_errors: int = 0          # 자동 교정 가능 후보 수
    applied_corrections: int = 0     # 실제 적용된 교정 수
    errors_before: int = 0           # 교정 전 오류 행 수
    errors_after: int = 0            # 교정 후 오류 행 수
    accepted: bool = False           # 오류가 줄어 채택되었는가
    auto_fix_rate: float = 0.0       # applied / fixable
    corrections: list[Correction] = Field(default_factory=list)


class AgentState(BaseModel):
    """워크플로우 전역 상태."""

    request_id: str
    current_stage: str = "start"
    current_agent: Optional[str] = None

    # 입력 (mock 메일)
    raw_email_subject: Optional[str] = None
    raw_email_body: Optional[str] = None

    # 분석 결과
    extracted_requirements: Optional[ExtractedRequirements] = None
    validation_rules: Optional[ValidationRule] = None

    # RAG (선택)
    rag_required: bool = False
    reference_documents: list[dict[str, Any]] = Field(default_factory=list)

    # 엑셀 처리
    uploaded_excel_files: list[str] = Field(default_factory=list)
    validation_result: Optional[ExcelValidationResult] = None
    self_correction: Optional[SelfCorrectionResult] = None
    merged_file: Optional[str] = None
    merged_rows: int = 0
    error_report: Optional[str] = None

    # 고수준 추론 로그 (ToT / Self-Correction / Planning) — 시연 영상·보고서용
    reasoning_log: list[str] = Field(default_factory=list)

    # 결과
    result_summary: Optional[str] = None

    # 추적
    current_node: Optional[str] = None
    langfuse_trace_id: Optional[str] = None
    agent_handoff_history: list[str] = Field(default_factory=list)
    error_state: Optional[dict[str, Any]] = None

    # 직렬화 제외: 검증 단계에서 읽은 엑셀 DataFrame 을 병합 단계로 전달
    _loaded_files: list[Any] = PrivateAttr(default_factory=list)
    # Self-Correction 채택 후 재검증 결과(잔여 오류) — 병합/오류보고서에서 사용
    _post_result: Optional[ExcelValidationResult] = PrivateAttr(default=None)

    def handoff(self, agent: str, node: str) -> None:
        """Agent 전환 기록."""
        self.current_agent = agent
        self.current_node = node
        self.agent_handoff_history.append(f"{agent}:{node}")

    def reason(self, line: str) -> None:
        """고수준 추론 로그 1줄 기록 (PLAN/BRANCH/EVALUATE/CRITIQUE/REVISE 등)."""
        self.reasoning_log.append(line)
