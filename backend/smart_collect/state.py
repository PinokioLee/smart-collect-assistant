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


class ColumnSpec(BaseModel):
    """취합 양식(엑셀)의 컬럼 1개 정의.

    자연어 요청을 LLM(또는 휴리스틱)이 이 구조로 '설계'하고,
    결정론 코드가 이 정의로 엑셀 양식을 생성하고 검증 규칙으로 변환한다.
    """

    name: str                                   # 컬럼명 (예: 프로젝트번호)
    dtype: str = "text"                          # text / date / number / code
    required: bool = False                       # 필수 입력 여부
    allowed_values: list[str] = Field(default_factory=list)  # dtype=code 일 때 허용값
    date_format: str = "YYYY-MM-DD"              # dtype=date 일 때 표기 형식
    example: Optional[str] = None                # 예시값 (양식 예시행/안내에 사용)
    description: Optional[str] = None            # 작성 안내 문구


class TemplateSpec(BaseModel):
    """AI가 설계한 취합 양식 전체 정의(=검증 계약).

    이 스펙 하나로 (1) 배포용 엑셀 양식 생성 (2) 회신 검증 규칙 생성을
    모두 결정론적으로 파생한다 — '보낸 양식 = 검증 기준' 라운드트립의 단일 출처.
    """

    title: str = "취합 양식"                      # 양식 제목 (시트/파일명 기반)
    purpose: Optional[str] = None                # 취합 목적
    deadline: Optional[str] = None               # 제출 기한 (있으면)
    columns: list[ColumnSpec] = Field(default_factory=list)
    duplicate_keys: list[str] = Field(default_factory=list)  # 중복 판정 키
    notes: list[str] = Field(default_factory=list)           # 작성 주의사항
    source: str = "heuristic"                    # 판단 주체: llm / heuristic


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
    source: str = "rule"  # 판단 주체: llm(LLM 제안) / rule(결정론 폴백)
    rationale: Optional[str] = None  # LLM 이 제안한 경우 근거(한 줄)
    verified: bool = True  # 결정론 게이트(허용값/날짜형식) 통과 여부


class ReasoningStep(BaseModel):
    """에이전트 실행 1스텝의 구조화 로그 — 시연/발표 증거용.

    reasoning_log(문자열)와 별개로, 화면 타임라인·트레이스 파일에서
    '어느 에이전트가 / 어떤 국면에서 / 무엇을 / 무엇으로 판단했는지'를 담는다.
    """

    seq: int
    agent: str          # 예: Supervisor Agent
    node: str           # 예: PlanningNode
    phase: str          # PLAN / BRANCH / EVALUATE / SELECT / VALIDATE / CRITIQUE / PROPOSE / REVISE / RE-VALIDATE / ACCEPT / REPORT
    decision: str       # 사람이 읽는 한 줄 판단 요약
    actor: str = "rule"  # 판단 주체: llm / rule
    detail: dict[str, Any] = Field(default_factory=dict)


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
    # True 이면 validation_rules 가 '생성한 양식(TemplateSpec)'에서 확정된 계약이므로
    # Supervisor 는 ToT 로 규칙을 재도출하지 않고 그대로 사용한다(라운드트립).
    template_locked: bool = False
    template_id: Optional[str] = None
    # Supervisor(LLM) 의 실행 계획·리스크 판단 (에이전틱 계획 단계)
    supervisor_plan: Optional[dict[str, Any]] = None

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
    # 구조화 추론 스텝 — 화면 타임라인 + 트레이스 증거 파일용
    reasoning_steps: list[ReasoningStep] = Field(default_factory=list)
    # 실행 트레이스 증거 파일 경로 (data/traces/{request_id}.json|.md)
    trace_files: dict[str, str] = Field(default_factory=dict)

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

    def step(
        self,
        phase: str,
        decision: str,
        *,
        actor: str = "rule",
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        """구조화 추론 스텝 1건 기록 (현재 agent/node 기준). 화면·트레이스 증거용."""
        self.reasoning_steps.append(
            ReasoningStep(
                seq=len(self.reasoning_steps) + 1,
                agent=self.current_agent or "-",
                node=self.current_node or "-",
                phase=phase,
                decision=decision,
                actor=actor,
                detail=detail or {},
            )
        )
