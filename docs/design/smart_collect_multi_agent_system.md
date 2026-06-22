### Agent 페르소나 및 시스템 프롬프트 Identity

Agent 정의

| 항목 | 정의 내용 |
|---|---|
| Agent 이름 | Smart Collect Multi-Agent System |
| 주요 역할 | Supervisor Agent가 전체 취합 업무 흐름을 제어하고, Email Agent, Requirement Analysis Agent, RAG Reference Agent, Guide Draft Agent, Submission Tracking Agent, Excel Validation Agent, Report Agent가 역할을 분담하여 취합 요청 메일 분석, 작성 가이드 생성, 제출 현황 추적, 엑셀 파일 병합 및 검증을 지원하는 업무 자동화 시스템 |
| 핵심 목표 | 반복적인 엑셀 취합 업무 시간을 줄이고, 작성 기준을 표준화하며, 제출 누락과 데이터 오류를 최소화한다. |
| 톤앤매너 | 명확하고 친절한 업무 지원자 톤. 작성자에게는 쉽게 설명하고, 관리자에게는 요약·오류·다음 조치를 구조화하여 보고한다. |
| 제약 사항 | 민감 정보 또는 개인정보를 외부로 임의 전송하지 않는다. 사용자의 승인 없이 메일, 최종 파일을 발송하지 않는다. 불확실한 내용은 임의로 판단하지 않고 확인 필요 항목으로 표시한다. 엑셀 원본 데이터는 임의로 삭제하거나 변경하지 않는다. |

***

### Agent System Prompt 핵심 내용

```text
당신은 회사 내부 취합 업무를 지원하는 Smart Collect Multi-Agent System입니다.

당신의 역할은 단일 Agent가 모든 업무를 처리하는 것이 아니라, Supervisor Agent가 전체 업무 흐름을 관리하고 여러 전문 Agent가 역할을 나누어 협업하도록 하는 것입니다.

전체 Agent 구성은 다음과 같습니다.

1. Supervisor Agent
- 전체 업무 흐름을 제어합니다.
- 현재 상태를 판단하고 다음에 실행할 전문 Agent를 선택합니다.
- 사용자 승인 여부, 오류 발생 여부, 다음 조치 필요 여부를 관리합니다.

2. Email Agent
- Gmail MCP를 통해 메일 검색, 메일 읽기, 첨부파일 수집, 메일 초안 생성을 수행합니다.
- 메일 발송은 반드시 사용자 승인 후 진행합니다.

3. Requirement Analysis Agent
- 취합 요청 메일에서 요청 목적, 작성 항목, 제출 기한, 작성 대상자, 주의사항을 추출합니다.
- 불확실한 내용은 추측하지 않고 "확인 필요"로 표시합니다.

4. RAG Reference Agent
- 업무 매뉴얼, 과거 취합 사례, 컬럼 정의서, 검증 규칙처럼 내부 기준 확인이 필요한 문서를 검색합니다.
- RAG는 모든 기능에 사용하지 않고, 내부 기준이 필요한 경우에만 제한적으로 사용합니다.

5. Guide Draft Agent
- 분석 결과와 RAG 참고 문서를 바탕으로 작성자용 작성 가이드와 메일 초안을 생성합니다.
- 작성자용 안내문은 쉽고 명확하게 작성합니다.

6. Submission Tracking Agent
- Gmail 회신 메일과 첨부파일을 기준으로 제출자, 미제출자, 지연 제출자를 구분합니다.
- 미제출자에게 보낼 리마인드 메일 문구를 생성합니다.

7. Excel Validation Agent
- 엑셀 파일의 필수값 누락, 형식 오류, 중복 데이터, 코드값 오류를 검증합니다.
- 엑셀 병합과 데이터 검증은 LLM 판단이 아니라 pandas와 openpyxl 기반의 규칙 기반 로직으로 처리합니다.
- 엑셀 원본 파일은 보존하고, 결과 파일은 별도로 생성합니다.

8. Report Agent
- 제출 현황, 검증 결과, 병합 결과를 요약하여 최종 보고서를 생성합니다.
- 최종 응답은 요약, 상세 결과, 확인 필요 사항, 다음 조치 순서로 제공합니다.

항상 다음 원칙을 지켜야 합니다.

1. Supervisor Agent가 전체 업무 흐름과 상태를 관리합니다.
2. 각 전문 Agent는 자신의 역할에 맞는 작업만 수행합니다.
3. Gmail MCP를 통해 메일 검색, 메일 읽기, 첨부파일 수집, 메일 초안 생성을 수행합니다.
4. 메일 발송은 반드시 사용자 승인 후 진행합니다.
5. RAG는 업무 기준 확인이 필요한 단계에만 제한적으로 사용합니다.
6. 엑셀 검증과 병합은 LLM 판단이 아니라 규칙 기반 로직으로 처리합니다.
7. 모든 주요 Agent 실행, LLM 호출, RAG 검색 결과, Gmail MCP Tool Call, 오류 발생 지점은 Langfuse Trace로 기록합니다.
8. 회사 내부 정보, 개인정보, 업무상 민감한 정보는 외부로 노출하지 않습니다.
```

***

### 워크플로우 및 오케스트레이션 Workflow & Logic

#### 2.1 처리 로직

#### Step 1 Input Analysis

사용자 입력 또는 Gmail MCP를 통해 수신된 메일을 분석하여 현재 요청이 어떤 업무인지 분류한다.

분류 대상은 다음과 같다.

| 분류 | 설명 |
|---|---|
| 취합 요청 메일 검색 | Email Agent가 Gmail MCP를 통해 취합 요청 관련 메일을 검색 |
| 취합 요청 분석 | Requirement Analysis Agent가 요청 메일에서 목적, 작성 항목, 마감일, 작성 대상자를 추출 |
| 기준 문서 검색 | RAG Reference Agent가 업무 매뉴얼, 컬럼 정의서, 검증 규칙, 과거 취합 사례를 검색 |
| 작성 가이드 생성 | Guide Draft Agent가 작성자에게 보낼 쉬운 작성 방법 안내문 생성 |
| 메일 초안 생성 | Guide Draft Agent와 Email Agent가 작성자에게 발송할 취합 요청 메일 초안 작성 |
| 사용자 승인 | Supervisor Agent가 메일 발송, 최종 파일 생성 전 사용자 승인 여부 확인 |
| 메일 발송 | Email Agent가 승인된 메일을 Gmail MCP를 통해 발송 |
| 제출 현황 확인 | Submission Tracking Agent가 Gmail 회신 메일과 첨부파일을 기준으로 제출 현황 확인 |
| 미제출자 리마인드 | Submission Tracking Agent가 미제출자에게 보낼 재안내 문구 생성 |
| 엑셀 파일 수집 | Email Agent 또는 Submission Tracking Agent가 회신 메일에서 제출된 엑셀 파일 수집 |
| 엑셀 병합 | Excel Validation Agent가 검증 통과 파일을 하나의 취합 파일로 병합 |
| 데이터 검증 | Excel Validation Agent가 필수값 누락, 중복, 날짜 형식, 코드값 오류 확인 |
| 결과 보고 | Report Agent가 최종 취합 결과와 오류 내역을 보고서로 생성 |
| 실행 추적 | Supervisor Agent가 전체 Agent 실행 흐름을 Langfuse로 기록 |

***

#### Step 2 Tool Selection

Supervisor Agent는 사용자 의도와 현재 상태에 따라 필요한 전문 Agent와 도구를 선택한다.

| 사용자 의도 | 선택 도구 |
|---|---|
| Gmail에서 취합 요청 메일을 찾고 싶음 | Email Agent / search_collection_emails |
| 취합 요청 메일을 읽고 싶음 | Email Agent / read_email |
| 취합 요청 메일을 분석하고 싶음 | Requirement Analysis Agent / analyze_collection_email |
| 과거 취합 사례나 업무 기준을 참고하고 싶음 | RAG Reference Agent / retrieve_reference_documents |
| 작성자용 안내문을 만들고 싶음 | Guide Draft Agent / generate_writing_guide |
| 작성자에게 보낼 메일을 만들고 싶음 | Guide Draft Agent + Email Agent / create_request_mail |
| 작성 대상자를 등록하고 싶음 | Supervisor Agent / load_recipient_list |
| 메일 발송 승인을 받고 싶음 | Supervisor Agent / request_human_approval |
| 승인된 메일을 발송하고 싶음 | Email Agent / send_approved_email |
| 제출 여부를 확인하고 싶음 | Submission Tracking Agent / track_submission_status |
| 미제출자에게 재촉하고 싶음 | Submission Tracking Agent / generate_reminder_message |
| 제출된 엑셀 파일을 수집하고 싶음 | Email Agent / collect_excel_attachments |
| 여러 엑셀 파일을 합치고 싶음 | Excel Validation Agent / merge_excel_files |
| 엑셀 데이터 오류를 확인하고 싶음 | Excel Validation Agent / validate_excel_data |
| 최종 보고서를 만들고 싶음 | Report Agent / generate_result_report |
| 실행 이력을 추적하고 싶음 | Supervisor Agent / trace_with_langfuse |

***

#### Step 3 Execution & Response

Supervisor Agent는 각 전문 Agent의 실행 결과를 종합하여 최종 응답을 생성한다.

최종 응답은 다음 구조를 따른다.

```text
1. 요약
- 현재 처리 결과를 한눈에 보여준다.

2. 상세 결과
- 메일 분석 결과, RAG 검색 결과, 제출 현황, 오류 목록, 생성 파일 등을 구체적으로 제공한다.

3. 확인 필요 사항
- AI가 확신할 수 없는 항목 또는 사용자 승인이 필요한 항목을 표시한다.

4. 다음 조치
- 사용자가 다음에 해야 할 일을 단계별로 안내한다.

5. 실행 추적 정보
- 현재 실행 Agent, LangGraph 현재 Node, Langfuse Trace ID를 제공한다.
```

***

#### 2.2 상태 관리

Supervisor Agent는 취합 업무 1건을 하나의 Job으로 관리한다.

#### 상태 정의

| 상태명 | 설명 |
|---|---|
| request_id | 취합 요청 건을 구분하는 고유 ID |
| raw_email | 원본 취합 요청 메일 내용 |
| gmail_message_id | Gmail MCP를 통해 조회한 원본 메일 ID |
| extracted_requirements | Requirement Analysis Agent가 추출한 요청 목적, 작성 항목, 마감일, 주의사항 |
| recipient_list | 작성 대상자 목록 |
| deadline | 제출 마감일 |
| attachment_template | 작성 양식 파일 |
| reference_documents | RAG Reference Agent가 검색한 업무 매뉴얼, 과거 사례, 컬럼 정의서, 검증 규칙 |
| writing_guide | Guide Draft Agent가 생성한 작성자용 작성 가이드 |
| mail_draft | Guide Draft Agent와 Email Agent가 생성한 메일 초안 |
| approval_status | 사용자 승인 상태 |
| send_status | Email Agent의 메일 발송 상태 |
| submission_status | Submission Tracking Agent가 확인한 작성자별 제출 상태 |
| submitted_files | 제출된 엑셀 파일 목록 |
| validation_result | Excel Validation Agent의 데이터 검증 결과 |
| merged_file | 최종 병합 파일 |
| result_report | Report Agent가 생성한 최종 결과 보고서 |
| supervisor_decision_log | Supervisor Agent의 Agent 선택 및 분기 판단 이력 |
| agent_handoff_history | Agent 간 작업 전달 이력 |
| current_agent | 현재 실행 중인 전문 Agent |
| current_node | 현재 실행 중인 LangGraph Node |
| langfuse_trace_id | Langfuse 실행 추적 ID |
| error_state | 오류 발생 여부 및 오류 내용 |

***

#### LangGraph Node / Edge 흐름

```text
START
  ↓
Supervisor Agent
  ↓
Email Agent
  - Gmail MCP Email Search
  - Gmail MCP Email Read
  ↓
Requirement Analysis Agent
  - Email Analysis
  - Requirement Extraction
  ↓
Supervisor Agent
  - Planning & Validation
  ↓
RAG Reference Agent
  - Reference Document Search
  - Validation Rule Search
  ↓
Guide Draft Agent
  - Writing Guide Generation
  - Mail Draft Generation
  ↓
Supervisor Agent
  - Human Review
  - Human Approval
  ↓
Email Agent
  - Gmail MCP Send
  ↓
Submission Tracking Agent
  - Submission Tracking
  - Reminder Check
  ↓
Email Agent
  - Excel Attachment Collection
  ↓
Excel Validation Agent
  - Excel Validation
  - Excel Merge
  ↓
Report Agent
  - Result Report Generation
  ↓
Supervisor Agent
  - Final Response
  - Langfuse Trace Logging
  ↓
END
```

***

#### LangGraph 분기 처리

| 조건 | 이동 노드 |
|---|---|
| Gmail에서 취합 요청 메일을 찾지 못함 | Supervisor Agent → Human Review |
| 메일 분석 결과에 마감일이 없음 | Supervisor Agent → Human Review |
| 작성 항목 또는 작성 기준이 불명확함 | Supervisor Agent → RAG Reference Agent |
| RAG 검색 결과 신뢰도가 낮음 | Supervisor Agent → Human Review |
| 작성 대상자 목록이 없음 | Supervisor Agent → Recipient Load |
| 사용자 승인이 완료되지 않음 | Supervisor Agent → Human Approval 대기 |
| 사용자가 발송을 승인함 | Supervisor Agent → Email Agent |
| 미제출자가 있음 | Supervisor Agent → Submission Tracking Agent |
| 모든 작성자가 제출 완료 | Supervisor Agent → Email Agent 또는 Excel Validation Agent |
| 엑셀 오류가 있음 | Excel Validation Agent → Report Agent 오류 보고 |
| 검증 통과 | Excel Validation Agent → Excel Merge |
| 병합 완료 | Supervisor Agent → Report Agent |
| 오류 발생 | Supervisor Agent가 Langfuse Trace에 오류 기록 후 Human Review 이동 |

***

### 도구 Tools 및 함수 명세 Capability

| 도구명 Function Name | 기능 설명 Description | 입력 파라미터 Input Schema | 출력 데이터 Output |
|---|---|---|---|
| route_task_by_supervisor | Supervisor Agent가 현재 상태를 분석하고 다음 실행 Agent를 결정한다. | agent_state: dict / user_intent: string | next_agent: string / next_node: string / reason: string |
| search_collection_emails | Email Agent가 Gmail MCP를 통해 취합 요청 관련 메일을 검색한다. | query: string / date_range: string | email_list: list / matched_count: number |
| read_email | Email Agent가 Gmail MCP를 통해 선택한 메일 본문과 첨부파일 정보를 읽는다. | gmail_message_id: string | email_subject: string / email_body: string / attachments: list |
| analyze_collection_email | Requirement Analysis Agent가 취합 요청 메일을 분석하여 목적, 작성 항목, 마감일, 주의사항을 추출한다. | email_subject: string / email_body: string / attachments: list | request_summary: string / fields: list / deadline: string / cautions: list / missing_info: list |
| retrieve_reference_documents | RAG Reference Agent가 업무 매뉴얼, 과거 취합 메일, 컬럼 정의서, 검증 규칙 등 관련 문서를 검색한다. | query: string / document_type: string / top_k: number | retrieved_docs: list / source_info: list / confidence_score: number |
| generate_writing_guide | Guide Draft Agent가 분석된 요청 내용과 참고 문서를 바탕으로 작성자용 작성 가이드를 생성한다. | request_summary: string / fields: list / deadline: string / cautions: list / retrieved_docs: list | guide_title: string / guide_body: string / field_instructions: list |
| create_request_mail | Guide Draft Agent가 작성자에게 발송할 취합 요청 메일 초안을 생성한다. | guide_body: string / recipient_group: list / deadline: string / attachment_name: string | mail_subject: string / mail_body: string |
| load_recipient_list | Supervisor Agent가 작성 대상자 목록을 불러오거나 등록한다. | file_path: string 또는 recipients: list | recipient_list: list / invalid_recipients: list |
| request_human_approval | Supervisor Agent가 메일 발송 또는 최종 파일 생성 전 사용자 승인을 요청한다. | request_id: string / approval_target: string / preview_data: dict | approval_status: string / approved_by: string / approved_at: string |
| send_approved_email | Email Agent가 사용자 승인 후 Gmail MCP를 통해 메일을 발송한다. | draft_id: string 또는 mail_payload: dict | send_result: list / failed_list: list |
| track_submission_status | Submission Tracking Agent가 Gmail 회신 메일과 제출 파일을 기준으로 작성자별 제출 여부를 확인한다. | recipient_list: list / gmail_thread_data: list / deadline: string | submitted_list: list / missing_list: list / late_list: list / submission_rate: number |
| generate_reminder_message | Submission Tracking Agent가 미제출자에게 보낼 리마인드 메일 문구를 생성한다. | missing_list: list / deadline: string / guide_summary: string | reminder_mail_subject: string / reminder_mail_body: string |
| collect_excel_attachments | Email Agent가 Gmail 회신 메일에서 제출된 엑셀 첨부파일을 수집한다. | request_id: string / gmail_thread_data: list / recipient_list: list | submitted_files: list / unmatched_files: list |
| validate_excel_data | Excel Validation Agent가 제출된 엑셀 파일의 필수값 누락, 형식 오류, 중복 여부를 검증한다. | excel_files: list / validation_rules: dict | valid_rows: list / error_rows: list / duplicate_rows: list / error_report: dict |
| update_common_fields | Excel Validation Agent가 여러 엑셀 파일에 공통적으로 들어가는 항목을 일괄 업데이트한다. | excel_files: list / target_field: string / old_value: string / new_value: string | updated_files: list / update_count: number / error_list: list |
| merge_excel_files | Excel Validation Agent가 여러 엑셀 파일을 하나의 최종 취합 파일로 병합한다. | excel_files: list / merge_key: list / add_metadata: boolean | merged_file_path: string / total_rows: number / source_file_count: number |
| generate_result_report | Report Agent가 제출 현황, 검증 결과, 최종 병합 결과를 요약한 보고서를 생성한다. | submission_status: dict / validation_result: dict / merged_file_path: string | report_summary: string / report_file_path: string |
| trace_with_langfuse | Supervisor Agent가 Agent 실행 단계, LLM 호출, RAG 검색, Tool Call, 오류 정보를 Langfuse에 기록한다. | request_id: string / agent_name: string / node_name: string / input_summary: dict / output_summary: dict / error: dict | langfuse_trace_id: string / trace_status: string |

***

### 지식 베이스 및 메모리 전략 Context & Memory

#### 4.1 RAG 검색 증강 생성 전략

본 프로젝트에서는 RAG를 전체 기능에 무조건 적용하지 않고, 회사 내부 기준이나 과거 사례를 참고해야 하는 기능에 제한적으로 적용한다.

RAG는 Supervisor Agent가 필요 여부를 판단한 뒤 RAG Reference Agent를 호출하는 방식으로 사용한다.

LLM은 자연어 분석과 문서 생성에는 강점이 있지만, 회사 내부 규칙이나 기존 업무 기준을 모르는 상태에서는 부정확한 답변을 생성할 수 있다. 따라서 작성 가이드 생성, 컬럼 설명, 입력 기준 안내, 결과 보고서 작성처럼 내부 기준이 필요한 부분에 RAG를 활용한다.

반면 엑셀 병합, 필수값 검증, 날짜 형식 검증, 중복 데이터 확인은 LLM이 아니라 Excel Validation Agent가 pandas와 openpyxl 기반의 규칙 기반 로직으로 처리한다.

#### RAG 적용 여부

| 기능 | RAG 적용 여부 | 이유 |
|---|---|---|
| 취합 요청 메일 분석 | 부분 적용 | 메일 내용만으로 분석 가능하지만, 과거 유사 요청 참고 시 Requirement Analysis Agent의 분석 정확도 향상 |
| 작성 가이드 생성 | 적용 | Guide Draft Agent가 과거 작성 가이드, 업무 매뉴얼, 표준 양식을 참고해야 함 |
| 컬럼 설명 및 입력 규칙 안내 | 적용 | RAG Reference Agent가 컬럼 정의서와 검증 규칙 문서를 검색해야 함 |
| 메일 초안 생성 | 부분 적용 | 회사 내부 메일 톤과 기존 안내문 사례 참고 가능 |
| 제출 현황 확인 | 미적용 | Submission Tracking Agent가 Gmail 회신과 시스템 데이터 기반으로 판단 |
| 엑셀 데이터 검증 | 미적용 | Excel Validation Agent가 필수값, 중복, 날짜 형식을 규칙 기반으로 검증 |
| 엑셀 병합 | 미적용 | Excel Validation Agent가 pandas/openpyxl 기반으로 처리 |
| 최종 결과 보고서 작성 | 부분 적용 | Report Agent가 기존 보고서 양식을 참고하여 보고 문장 생성 가능 |

#### 참조 데이터 소스

| 데이터 소스 | 설명 |
|---|---|
| 과거 취합 요청 메일 | 기존에 작성했던 취합 요청 메일 사례 |
| 작성 가이드 샘플 | 작성자에게 보낸 과거 안내문 |
| 표준 엑셀 양식 | 회사에서 자주 사용하는 취합 양식 |
| 컬럼 정의서 | 각 엑셀 컬럼의 의미, 입력 규칙, 예시 |
| 검증 규칙 문서 | 필수값, 날짜 형식, 코드값, 중복 기준 등 |
| 부서 및 담당자 목록 | 작성 대상자 정보 |
| 업무 매뉴얼 | 취합 업무 처리 절차 |

***

#### 청킹 Chunking 방식

| 항목 | 방식 |
|---|---|
| 메일 데이터 | 메일 1건 단위로 저장하고, 제목/본문/첨부 설명을 함께 보관 |
| 업무 매뉴얼 | 제목 단위 또는 절 단위로 분리 |
| 엑셀 컬럼 정의서 | 컬럼 1개를 하나의 단위로 분리 |
| 검증 규칙 문서 | 검증 항목 단위로 분리 |
| 작성 가이드 샘플 | 취합 업무 유형별로 분리 |
| 청크 크기 | 약 500~1,000 토큰 |
| 청크 중복 | 앞뒤 문맥 유지를 위해 약 100~150 토큰 중복 |

***

#### 임베딩 모델

| 항목 | 선정 내용 |
|---|---|
| 임베딩 모델 | Azure OpenAI Embedding Model 또는 사내 승인 임베딩 모델 |
| 선정 이유 | 회사 보안 정책을 준수하면서 한국어 업무 문서 검색에 활용 가능 |

***

#### Vector DB

| 항목 | 선정 내용 |
|---|---|
| Vector DB | FAISS 또는 Chroma |
| PoC 추천 | FAISS |
| 운영 단계 추천 | Chroma 또는 사내 승인 Vector DB |
| 선정 이유 | PoC에서는 설치와 테스트가 쉬운 FAISS가 적합하고, 운영 단계에서는 메타데이터 관리가 쉬운 Vector DB가 적합 |

***

#### 4.2 대화 메모리 Conversation History

#### 메모리 유형

| 메모리 유형 | 사용 여부 | 설명 |
|---|---|---|
| Window Buffer Memory | 사용 | Supervisor Agent가 최근 대화 몇 턴을 유지하여 현재 작업 흐름을 이해 |
| Summary Memory | 사용 | 취합 요청의 핵심 내용, 마감일, 대상자, 진행 상태를 요약 저장 |
| Long-term Memory | 제한적 사용 | 과거 취합 유형, 표준 작성 가이드, 검증 규칙 저장 |
| Agent Handoff Memory | 사용 | Supervisor Agent가 어떤 전문 Agent에게 어떤 작업을 넘겼는지 저장 |
| 전체 대화 저장 | 비권장 | 개인정보 및 업무 정보가 과도하게 저장될 수 있으므로 제한 필요 |

***

#### 저장 전략

| 항목 | 전략 |
|---|---|
| 세션 단위 저장 | 취합 요청 1건을 하나의 세션으로 관리 |
| 저장 대상 | 요청 요약, 작성 항목, 마감일, 대상자, 제출 상태, 검증 결과, Agent 실행 이력, Langfuse Trace ID |
| 저장 제외 | 불필요한 개인정보, 민감한 원문 전체, 첨부 파일 원본 전체 |
| 초기화 기준 | 취합 업무 완료 후 결과 보고서 생성 시 세션 종료 |
| 보관 기준 | 회사 보안 정책에 따라 기간 설정 |
| 사용자 승인 | 메일 발송, 최종 파일 저장 전 승인 필요 |

***

### 핵심 에이전트 기술 스택

| 구분 | 선정 전략/기술 | 선정 사유 |
|---|---|---|
| LLM Model | Azure OpenAI 기반 사내 승인 LLM 모델 | 회사 VDI 환경에서 외부 AI 사용이 제한될 수 있으므로, 사내 보안 정책을 준수할 수 있는 Azure API 기반 모델을 우선 사용한다. 한국어 메일 분석, 작성 가이드 생성, 요약 업무에 적합하다. |
| Agent Framework | LangGraph Multi-Agent Supervisor | 취합 업무는 메일 검색, 요청 분석, 기준 문서 검색, 작성 가이드 생성, 제출 추적, 엑셀 검증, 결과 보고처럼 서로 다른 전문성이 필요한 단계로 구성된다. 단일 Agent가 모든 작업을 처리하는 방식보다 Supervisor Agent가 전체 흐름을 제어하고 전문 Agent들이 역할별로 작업을 수행하는 멀티 에이전트 구조가 적합하다. |
| Multi-Agent Structure | Supervisor Agent + Specialist Agents | Supervisor Agent가 전체 계획, 상태, 분기, 승인 여부를 관리하고 Email Agent, Requirement Analysis Agent, RAG Reference Agent, Guide Draft Agent, Submission Tracking Agent, Excel Validation Agent, Report Agent가 역할을 분담한다. |
| Email Integration | Gmail MCP Adapter | Gmail 메일 검색, 메일 본문 분석, 첨부파일 수집, 메일 초안 생성, 승인 후 발송을 Email Agent에 연결한다. 실제 Gmail MCP 연결이 준비되지 않은 환경에서도 Mock Adapter로 동일한 흐름을 검증할 수 있도록 분리 설계한다. |
| Prompt Strategy | Agent Role Prompting + Few-Shot + Structured Prompt | 각 전문 Agent의 역할을 명확히 분리하고, 과거 취합 메일 예시를 Few-Shot으로 제공하여 답변 품질을 높인다. 도구 선택이 필요한 업무는 구조화된 프롬프트를 통해 처리한다. |
| Planning Strategy | Supervisor Planning + Validation + Self-Correction Loop | Supervisor Agent가 요청 분석 후 실행 계획을 만들고, 마감일·작성 항목·승인 여부·검증 규칙 누락 여부를 확인한다. 누락된 정보가 있으면 Human Review 또는 RAG Reference Agent로 되돌리는 구조를 적용한다. |
| Output Parsing | Structured Output + JSON Mode | 메일 분석 결과, 작성 항목, 마감일, 작성 대상자, 검증 결과, Agent 실행 결과는 정형 데이터로 관리해야 하므로 JSON 형태로 출력한다. |
| RAG Strategy | RAG Reference Agent 기반 업무 매뉴얼, 과거 취합 메일, 표준 양식, 컬럼 정의서, 검증 규칙 검색 | LLM이 임의로 답변하지 않도록 회사 내부 기준 문서를 검색하여 답변 근거로 활용한다. 단, 모든 기능에 적용하지 않고 기준 문서가 필요한 기능에만 제한적으로 적용한다. |
| Excel Processing | Excel Validation Agent + Python pandas + openpyxl | 엑셀 데이터 병합, 필수값 검증, 중복 확인, 결과 파일 생성은 Excel Validation Agent가 담당한다. 엑셀 검증은 LLM 판단이 아니라 규칙 기반 로직으로 처리한다. |
| API Server | FastAPI | Multi-Agent 기능을 API 형태로 제공하기 좋고, React 화면 및 향후 사내 시스템과 연동하기 쉽다. |
| UI | React + TypeScript | Streamlit은 빠른 PoC에는 적합하지만 실제 업무 시스템 화면으로 확장하기에는 한계가 있다. React는 취합 요청 등록, 승인, 제출 현황 대시보드, 오류 보고서 확인 등 복잡한 화면 구성이 가능하다. |
| Scheduler | APScheduler 또는 Windows Task Scheduler | 마감 전 리마인드, 제출 현황 주기적 확인 같은 예약 작업에 활용할 수 있다. |
| Monitoring | Langfuse + Console Log + File Log | Langfuse를 통해 Supervisor Agent의 의사결정, 전문 Agent 호출, LLM 호출, RAG 검색 결과, Gmail MCP Tool Call, LangGraph Node 실행 흐름, 오류 발생 지점을 Trace로 기록한다. Console Log와 File Log는 기본 실행 상태와 오류 내역을 남기는 보조 로그로 사용한다. |
| Storage | SQLite 또는 사내 DB | PoC에서는 SQLite로 빠르게 구현하고, 운영 단계에서는 회사 내부 DB와 연동한다. |
| Security | 사용자 승인 기반 실행 + Agent 권한 분리 + 원본 파일 보존 + 로그 기록 | 메일 오발송, 데이터 손상, 민감 정보 노출을 방지하기 위해 모든 주요 실행 전 사용자 승인 단계를 둔다. 각 Agent는 자신의 역할에 필요한 도구만 사용하도록 제한한다. |

***

### Agent 처리 예시

#### 사용자 입력 예시

```text
Gmail에서 아래 취합 요청 메일을 분석해서 작성자들에게 보낼 작성 가이드를 만들어줘.

메일 제목:
2026년 6월 시스템 개선 요청사항 취합

메일 본문:
각 부서별 시스템 개선 요청사항을 첨부 양식에 작성하여 6월 12일 17시까지 회신 바랍니다.
작성 항목은 부서명, 담당자, 요청 시스템, 개선 요청 내용, 긴급도, 요청 사유입니다.
```

***

#### Agent 출력 예시

```json
{
  "request_id": "REQ-202606-001",
  "workflow_status": "guide_generated",
  "architecture_type": "multi_agent",
  "supervisor_agent": {
    "current_decision": "Guide Draft Agent 실행 완료 후 사용자 승인 단계로 이동",
    "next_agent": "Email Agent",
    "next_action": "메일 초안 생성 및 사용자 승인 대기"
  },
  "executed_agents": [
    "Email Agent",
    "Requirement Analysis Agent",
    "RAG Reference Agent",
    "Guide Draft Agent"
  ],
  "gmail_mcp_used": true,
  "gmail_message_id": "gmail_msg_001",
  "langgraph_current_node": "GuideGenerationNode",
  "request_summary": "2026년 6월 부서별 시스템 개선 요청사항을 취합하는 업무입니다.",
  "deadline": "2026-06-12 17:00",
  "required_fields": [
    "부서명",
    "담당자",
    "요청 시스템",
    "개선 요청 내용",
    "긴급도",
    "요청 사유"
  ],
  "rag_used": true,
  "retrieved_references": [
    {
      "title": "시스템 개선 요청사항 작성 가이드 샘플",
      "score": 0.91
    },
    {
      "title": "개선 요청 긴급도 입력 기준",
      "score": 0.87
    }
  ],
  "writing_guide": {
    "title": "2026년 6월 시스템 개선 요청사항 작성 안내",
    "body": "첨부된 엑셀 양식에 부서별 시스템 개선 요청사항을 작성해주세요. 긴급도는 상/중/하 중 하나로 입력해주세요. 제출 기한은 2026년 6월 12일 17시까지입니다."
  },
  "approval_required": true,
  "langfuse_trace_id": "trace_req_202606_001",
  "missing_info": [],
  "next_action": "사용자 승인 후 Email Agent가 Gmail MCP를 통해 메일 초안을 생성하고 발송 대기 상태로 전환합니다."
}
```

***

### 보안 및 승인 정책

| 구분 | 정책 |
|---|---|
| 메일 발송 | Email Agent가 초안을 생성하되, Supervisor Agent가 사용자 승인 여부를 확인한 뒤 실제 발송 |
| Gmail 접근 | Email Agent가 Gmail MCP Adapter를 통해 접근하며, 업무에 필요한 범위에서만 메일을 조회 |
| Agent 권한 분리 | 각 전문 Agent는 자신의 역할에 필요한 도구만 사용하며, 메일 발송과 최종 파일 생성은 Supervisor Agent 승인 흐름을 거친다. |
| 엑셀 수정 | Excel Validation Agent는 원본 파일을 보존하고 복사본에만 수정 적용 |
| 데이터 검증 | 오류 데이터는 자동 수정하지 않고 오류 보고서에 기록 |
| 개인정보 | 이름, 연락처, 이메일 등은 필요한 범위에서만 사용 |
| 로그 관리 | Supervisor Agent 실행 이력, Agent Handoff 이력, 발송 이력, 파일 처리 이력, Langfuse Trace ID를 기록 |
| 외부 전송 | 회사 승인 없는 외부 API 전송 금지 |
| RAG 문서 관리 | 업무 매뉴얼, 컬럼 정의서, 검증 규칙 등 내부 문서는 승인된 저장소에만 보관 |
| LLM 사용 | Azure OpenAI API 또는 사내 승인 LLM 환경을 우선 사용 |
| Langfuse 사용 | 민감 원문 전체를 그대로 남기지 않고, 입력·출력 요약과 실행 상태 중심으로 기록 |

***

### PoC 개발 환경 구성안

| 구분 | 구성 |
|---|---|
| 개발 언어 | Python, TypeScript |
| 프론트엔드 | React |
| 백엔드 | FastAPI |
| LLM 연동 | Azure OpenAI API |
| Multi-Agent 흐름 제어 | LangGraph Multi-Agent Supervisor |
| 이메일 연동 | Gmail MCP Adapter |
| 엑셀 처리 | pandas, openpyxl |
| 데이터 저장 | SQLite |
| 벡터 검색 | FAISS |
| RAG 문서 저장 | 로컬 문서 폴더 또는 사내 승인 저장소 |
| 모니터링 | Langfuse |
| 기본 로그 | Console Log, File Log |
| 실행 환경 | 사내 VDI 또는 승인된 개발 PC |
| 배포 방식 | PoC 단계에서는 로컬 실행, 운영 단계에서는 사내 서버 배포 검토 |

***

### 최종 요약

Smart Collect Multi-Agent System은 Gmail MCP, LangGraph Multi-Agent Supervisor, RAG, Langfuse를 결합하여 메일 기반 엑셀 취합 업무를 자동화하는 멀티 에이전트 업무 자동화 시스템이다.

본 시스템은 단일 Agent가 모든 작업을 처리하는 구조가 아니라, Supervisor Agent가 전체 업무 흐름과 상태를 관리하고 여러 전문 Agent가 역할을 나누어 처리하는 구조로 설계한다.

Email Agent는 Gmail MCP를 통해 메일 검색, 읽기, 첨부파일 수집, 메일 초안 생성을 담당한다.

Requirement Analysis Agent는 취합 요청 메일에서 목적, 작성 항목, 마감일, 작성 대상자를 추출한다.

RAG Reference Agent는 업무 매뉴얼, 과거 취합 메일, 컬럼 정의서, 검증 규칙 등 내부 기준 문서를 검색한다.

Guide Draft Agent는 분석 결과와 RAG 참고 문서를 기반으로 작성자용 가이드와 메일 초안을 생성한다.

Submission Tracking Agent는 Gmail 회신 메일과 제출 파일을 기준으로 제출 현황을 추적한다.

Excel Validation Agent는 pandas/openpyxl 기반 규칙 로직으로 엑셀 검증과 병합을 수행한다.

Report Agent는 제출 현황, 오류 내역, 병합 결과를 종합하여 최종 보고서를 생성한다.

모든 주요 LLM 호출, RAG 검색, Gmail MCP Tool Call, Agent Handoff, LangGraph Node 실행 흐름은 Langfuse로 추적하여 Agent의 판단 과정과 오류 발생 지점을 확인할 수 있도록 한다.

이를 통해 반복 취합 업무의 처리 시간을 줄이고, 작성 기준 불일치, 제출 누락, 데이터 오류를 최소화하는 것을 목표로 한다.
