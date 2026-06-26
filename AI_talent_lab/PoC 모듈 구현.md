PoC 모듈 구현
핵심 기능 PoC (Proof of Concept) 구현

### 핵심 구현 내용

이번 PoC 단계에서 실제 코드로 구현된 핵심 기능들을 **동작 원리**와 **사용 기술** 중심으로 상세히 기술합니다.

**1.1 에이전트 워크플로우 (Agent Workflow)**

* **구현 기능:** Supervisor Agent 기반 멀티 에이전트 워크플로우

  * Smart Collect Multi-Agent System은 단일 Agent가 모든 업무를 처리하는 구조가 아니라, Supervisor Agent가 전체 업무 흐름을 관리하고 전문 Agent들이 역할별 작업을 수행하는 구조로 구현하였다.

  * 구성 Agent는 다음과 같다.

```text
Supervisor Agent
Email Agent
Requirement Analysis Agent
RAG Reference Agent
Guide Draft Agent
Submission Tracking Agent
Excel Validation Agent
Report Agent
```

* Supervisor Agent는 현재 업무 상태를 확인한 뒤 다음에 실행할 Agent를 결정한다.

* Email 관련 기능은 현재 mock 입력, 작성 가이드/메일 초안 생성, 승인 후 mock 또는 Gmail API 발송 Adapter까지 구현되어 있다. 실제 Gmail 수신함 검색, 메일 읽기, 첨부파일 수집은 후속 확장 범위로 분리하였다.

* Requirement Analysis Agent는 취합 요청 메일에서 목적, 작성 항목, 제출 기한, 주의사항을 추출한다.

* RAG Reference 기능은 내부 기준 문서가 필요한 경우를 대비해 인터페이스와 로컬 키워드 검색 수준으로 구현하였다. FAISS/Embedding 기반 운영 RAG는 후속 확장 범위이다.

* Guide Draft Agent는 작성자용 작성 가이드와 메일 초안을 생성한다.

* Submission Tracking Agent는 제출자, 미제출자, 지연 제출자를 구분한다.

* Excel Validation Agent는 제출된 엑셀 파일을 검증하고 병합한다.

* Report Agent는 제출 현황, 오류 내역, 병합 결과를 최종 보고서 형태로 정리한다.

**1.1-1 에이전트별 적용 기술**

멘토 피드백을 반영하여 각 Agent가 어떤 기술을 사용했고, 그 기술을 어떤 방식으로 적용했는지 역할별로 정리한다. 1차 PoC에서 실제 구현된 범위와 후속 확장 범위를 구분하여 작성하였다.

| Agent | 담당 역할 | 사용 기술 | 적용 방식 |
| --- | --- | --- | --- |
| Supervisor Agent | 전체 흐름 제어, 다음 단계 선택, 검증 규칙 계획 | LangGraph StateGraph, AgentState, Supervisor Routing, Tree of Thoughts | `AgentState`의 현재 상태를 기준으로 Requirement Analysis -> Planning -> Excel Validation -> Self-Correction -> Merge -> Error Report -> Report 흐름을 제어한다. 검증 규칙은 Strict/Balanced/Loose 후보를 생성한 뒤 실제 업로드 컬럼과 비교하여 선택한다. |
| Requirement Analysis Agent | 취합 요청 메일 분석, 작성 항목/마감/주의사항 추출 | Azure OpenAI, 휴리스틱 폴백, Pydantic 구조화 모델, JSON Output Parsing | 메일 제목과 본문에서 `request_title`, `deadline`, `required_fields`, `cautions`, `missing_info`를 추출한다. Azure 키가 없거나 호출 실패 시 휴리스틱 분석으로 폴백하여 기본 PoC가 계속 동작한다. |
| Excel Validation Agent | 제출 엑셀 검증, 정상 데이터 병합, 오류 보고서 생성 | pandas, openpyxl, 결정론적 검증 규칙 | 필수값 누락, 날짜 형식 오류, 허용되지 않은 코드값, 중복 데이터를 규칙 기반으로 검증한다. 정상 행만 병합 파일로 저장하고, 오류 행은 별도 오류 보고서로 생성한다. |
| Self-Correction Agent | 안전한 오류 자동 교정 및 재검증 | Self-Refine/Self-Correction 패턴, 날짜 정규화, 코드값 매핑, 재검증 루프 | 날짜 형식과 코드값처럼 원본 의미가 보존되는 오류만 자동 교정한다. 교정 후 재검증하여 오류 수가 줄어든 경우만 채택하고, 필수값 누락/중복은 재제출 대상으로 남긴다. |
| Report Agent | 최종 결과 요약, 다음 조치 정리 | Pydantic 결과 객체, 템플릿 기반 리포트 생성, Console/File Log | 파일 수, 전체 행 수, 정상 행 수, 오류 유형, 생성 파일, 다음 조치를 관리자용 요약으로 정리한다. 실행 흐름은 `agent_handoff_history`와 `reasoning_log`로 확인할 수 있게 한다. |
| Guide Draft Agent | 작성자용 가이드와 요청 메일 초안 생성 | 요구사항 분석 결과, 템플릿 기반 문장 생성, FastAPI `/api/guide` | 추출된 작성 항목과 제출 기한을 바탕으로 작성 가이드와 요청 메일 초안을 생성한다. 실제 발송 전에는 사용자 승인 단계를 거치도록 분리하였다. |
| Submission Tracking Agent | 제출자/미제출자/지연 제출자 분류 | 규칙 기반 문자열 매칭, 샘플 작성자 목록, mock 제출 데이터 | 샘플 작성자 목록과 제출 파일명 또는 제출 식별자를 비교하여 제출 상태를 계산한다. 실제 Gmail 회신 메일 기반 추적은 후속 확장 범위이다. |
| Email Agent | 메일 초안 발송 Adapter 관리 | MockEmailAdapter, GmailApiEmailAdapter, Human-in-the-loop 승인 구조 | 기본값은 실제 발송 없는 mock 모드이다. `EMAIL_SEND_MODE=gmail`과 OAuth credentials가 설정된 경우에만 Gmail API로 발송한다. Gmail 수신함 검색/첨부 수집은 후속 Adapter 확장 범위이다. |
| RAG Reference Agent | 기준 문서 검색 인터페이스 제공 | 로컬 키워드 검색, `retrieve_reference_documents`, confidence score | 1차 PoC에서는 핵심 실행 경로에 필수로 넣지 않고, 작성 기준이 불명확한 경우 호출 가능한 검색 Tool로 분리하였다. FAISS/Embedding 기반 Vector Search는 후속 확장 범위이다. |

* **동작 원리:** Supervisor Agent가 상태값을 기준으로 다음 Agent를 선택한다.

  * 사용자가 취합 요청 분석을 실행하면 Supervisor Agent가 요청을 수신한다.

  * Supervisor Agent는 현재 상태값을 확인하여 Requirement Analysis, Planning, Excel Validation, Self-Correction, Merge, Error Report, Report 노드를 순차 실행한다.

  * 1차 PoC에서는 실제 Gmail 수신함을 검색하지 않고, 화면 또는 샘플 파일에서 입력된 취합 요청 메일 제목/본문을 분석한다.

  * Requirement Analysis Agent는 메일 제목과 본문에서 요청 목적, 작성 항목, 제출 기한, 주의사항을 추출한다.

  * Supervisor Agent는 분석 결과를 확인하여 내부 기준 문서가 필요한지 판단한다.

  * 단순히 메일 내용을 정리하는 수준이면 RAG를 호출하지 않는다.

  * 작성 항목의 의미가 불명확하거나, 컬럼 입력 기준, 코드값, 날짜 형식, 기존 안내문 톤이 필요한 경우에만 RAG Reference Agent를 호출한다.

  * 기준 문서가 필요한 경우를 대비해 `retrieve_reference_documents` 인터페이스를 제공하며, 현재 구현은 `docs/reference` 폴더의 로컬 키워드 검색이다.

  * Guide Draft Agent는 분석 결과와 참고 문서를 바탕으로 작성자용 가이드와 메일 초안을 생성한다.

  * 메일 발송 전에는 Supervisor Agent가 사용자 승인 상태를 확인한다.

  * 승인되지 않은 경우 Email Agent는 메일 발송을 수행하지 않는다.

  * 제출 이후 Submission Tracking Agent는 샘플 작성자 목록과 제출 식별자 또는 파일명을 기준으로 제출 현황을 확인한다.

  * Excel Validation Agent는 제출된 엑셀 파일에 대해 필수값 누락, 날짜 형식 오류, 중복 데이터, 코드값 오류를 규칙 기반으로 검증한다.

  * 검증 통과 파일은 병합하고, 오류 데이터는 오류 보고서에 기록한다.

  * Report Agent는 최종 제출 현황, 오류 내역, 병합 결과를 보고서로 생성한다.

* **주요 기술:** LangGraph Multi-Agent Supervisor, AgentState, Supervisor Routing, Agent Handoff, Azure OpenAI 폴백 구조, Structured Prompt, JSON Output Parsing, Console/File Log

***

**1.2 도구(Tool) 및 함수 연동**

* **구현 기능:** Excel Processing Tool, Guide/Submission Tool, Mock/Gmail 발송 Adapter, FastAPI 승인형 발송 API

  * PoC 단계에서는 사내 메일 시스템에 직접 연동하지 않고 mock 메일 입력과 파일 업로드로 핵심 취합 흐름을 검증하였다.

  * 실제 업무 환경에서는 사내 메일 시스템을 사용해야 하지만, 개발 단계에서는 보안 정책과 접근 권한 문제로 사내 메일 서버 직접 연동이 제한된다.

  * 실제 발송이 필요한 경우를 대비해 Gmail API OAuth 기반 발송 Adapter를 분리했지만, 기본 실행 모드는 `EMAIL_SEND_MODE=mock`이다.

  * 이 구조를 통해 향후 Gmail 수신함 검색, 사내 메일 MCP 또는 사내 메일 API로 교체할 수 있도록 설계하였다.

* **동작 원리:** 각 Agent는 자신의 역할에 맞는 Tool만 호출한다.

  * Email 관련 Tool은 현재 초안 생성과 승인 후 발송을 담당한다.

```text
create_request_mail
send_email
```

* Requirement Analysis Agent는 메일 분석 Tool을 호출한다.

```text
analyze_collection_email
```

* RAG Reference Agent는 내부 문서 검색 Tool을 호출한다.

```text
retrieve_reference_documents
```

* Guide Draft Agent는 작성 가이드와 메일 초안 생성 Tool을 호출한다.

```text
generate_writing_guide
create_request_mail
```

* Submission Tracking Agent는 제출 현황 확인 Tool을 호출한다.

```text
track_submission_status
generate_reminder_message
```

* Excel Validation Agent는 엑셀 검증 및 병합 Tool을 호출한다.

```text
validate_excel_data
merge_excel_files
update_common_fields
```

* Report Agent는 결과 보고서 생성 Tool을 호출한다.

```text
generate_result_report
```

* Supervisor Agent는 Agent 라우팅, 사용자 승인, 실행 추적을 담당한다.

```text
route_task_by_supervisor
request_human_approval
trace_with_langfuse
```

* 메일 발송은 반드시 사용자 승인 후에만 실행된다.

* 승인 전 상태에서는 `send_approved_email`이 호출되지 않도록 Supervisor Agent가 `approval_status`를 확인한다.

* 엑셀 검증과 병합은 LLM 판단에 맡기지 않고 pandas와 openpyxl 기반 규칙 로직으로 처리한다.

* 실행 추적은 Console/File Log와 `agent_handoff_history`, `reasoning_log`로 확인한다. Langfuse 정식 Trace는 환경 변수와 운영 설정이 준비된 뒤 확장할 수 있다.

* **주요 기술:** Email Adapter Pattern, Mock Adapter, Gmail API 발송 Adapter, Python, FastAPI, Pydantic, pandas, openpyxl, Custom Tool Definition, Human-in-the-loop Approval

***

**1.3 데이터 및 메모리 (RAG & Context)**

* **구현 기능:** 내부 기준 문서 기반 제한적 RAG 검색 구조

  * RAG는 전체 기능에 무조건 적용하지 않고, 내부 기준 문서가 필요한 단계에서만 사용한다.

  * 단순 취합 요청 메일 분석, 제출 현황 계산, 엑셀 검증, 엑셀 병합에는 RAG를 사용하지 않는다.

  * 작성 기준이 불명확하거나, 컬럼 입력 규칙, 코드값 기준, 날짜 형식, 기존 작성 가이드 예시가 필요한 경우에만 RAG Reference Agent를 호출한다.

* **동작 원리:** 1차 PoC에서는 RAG를 핵심 실행 경로에 넣지 않고, 기준 검색이 필요한 경우 호출 가능한 Tool 인터페이스로 분리하였다.

  * Requirement Analysis Agent가 메일을 분석한 뒤, Supervisor Agent는 다음 기준으로 RAG 호출 여부를 판단한다.

```text
작성 항목의 의미가 불명확한가?
컬럼별 입력 기준이 필요한가?
코드값 또는 날짜 형식 기준이 필요한가?
기존 작성 가이드 예시가 필요한가?
보고서 문장 형식 참고가 필요한가?
```

* 위 조건에 해당하지 않으면 RAG를 호출하지 않고 Guide Draft Agent가 메일 분석 결과만으로 작성 가이드를 생성한다.

* 현재 RAG Reference Tool은 다음 위치의 로컬 문서를 키워드 기반으로 검색한다.

```text
docs/reference/
```

* 검색 결과는 `retrieved_docs`, `source_info`, `confidence_score`를 포함하여 반환한다.

* 검색 결과 신뢰도가 낮은 경우 운영 단계에서는 Human Review로 연결하도록 확장할 수 있다.

* **주요 기술:** 로컬 키워드 검색, RAG Reference Tool 인터페이스, Structured Context Injection 설계. FAISS, Azure OpenAI Embedding, Vector Search, Metadata Filtering은 후속 확장 범위이다.

***

### 주요 문제 해결 및 기술 리서치

구현 과정에서 마주친 기술적 문제와 이를 해결하기 위해 **찾아본 자료(리서치)** 및 **적용한 방법**을 기록합니다.

| **이슈 구분**                 | **문제 상황 및 원인**                                                                                                                                                                | **리서치 및 해결 과정 (Reference & Solution)**                                                                                                                                                                                                                                                                                               |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **멀티 에이전트 구조 설계**         | 엑셀 취합 업무는 메일 검색, 요청 분석, 기준 확인, 안내문 작성, 제출 추적, 엑셀 검증, 결과 보고처럼 성격이 다른 작업들이 순차적으로 연결된다. 각 단계에서 사용하는 도구와 판단 기준이 다르기 때문에 Agent별 책임을 분리할 필요가 있었다.                                   | **리서치:** LangGraph의 Supervisor 기반 Multi-Agent 구조와 Agent Handoff 방식을 검토하였다. **적용:** Supervisor Agent가 전체 흐름과 상태를 관리하고, Email Agent, Requirement Analysis Agent, RAG Reference Agent, Guide Draft Agent, Submission Tracking Agent, Excel Validation Agent, Report Agent가 역할별로 작업을 수행하도록 분리하였다. 각 Agent는 자신의 역할에 맞는 Tool만 사용하도록 설계하였다. |
| **Supervisor Routing 기준** | 멀티 에이전트 구조에서는 어떤 Agent를 언제 호출할 것인지가 명확해야 한다. 라우팅 기준이 없으면 Agent 선택이 프롬프트 응답에만 의존하게 되고, 동일한 업무에서도 실행 흐름이 달라질 수 있다.                                                              | **리서치:** LangGraph State 기반 라우팅과 조건 분기 방식을 검토하였다. **적용:** `route_task_by_supervisor` 함수를 설계하여 현재 상태값을 기준으로 다음 Agent를 결정하도록 하였다. 예를 들어 `gmail_message_id`가 없으면 Email Agent, `extracted_requirements`가 없으면 Requirement Analysis Agent, `approval_status=false`이면 Human Approval 단계로 이동하도록 조건을 분리하였다.                                   |
| **사내 메일 연동 제약**           | 실제 운영 환경에서는 사내 메일 시스템을 연동해야 하지만, PoC 개발 단계에서는 보안 정책과 접근 권한 문제로 사내 메일 서버에 직접 접근하기 어렵다. 또한 실제 업무 메일 원문과 첨부파일을 개발 환경에서 사용하는 것은 보안상 제한이 있다.                                       | **리서치:** 사내 메일 직접 연동 전 단계에서 동일한 업무 흐름을 검증할 수 있는 Adapter 방식을 검토하였다. **적용:** PoC에서는 mock 메일 입력과 파일 업로드로 취합 흐름을 검증하고, 승인 후 발송은 `MockEmailAdapter`와 `GmailApiEmailAdapter`로 분리하였다. Gmail 수신함 검색/읽기/첨부 수집은 후속 Adapter 확장 범위로 남겼다.                                                                                  |
| **메일 발송 승인 통제**           | 메일 발송은 실제 수신자에게 영향을 주는 작업이다. Agent가 메일 초안 생성과 실제 발송을 같은 흐름에서 자동 처리하면 오발송이 발생할 수 있다.                                                                                           | **리서치:** Human-in-the-loop 승인 구조를 검토하였다. **적용:** Email Agent는 메일 초안까지만 생성하고, Supervisor Agent가 `approval_status`를 확인한 뒤 승인된 경우에만 `send_approved_email`을 호출하도록 분리하였다. 승인 전 상태에서는 발송 Node로 이동하지 않도록 LangGraph 분기 조건을 추가하였다.                                                                                                            |
| **RAG 적용 범위 조정**          | 단순 취합 요청 메일을 분석하고 작성자용 안내문을 생성하는 기본 흐름에는 RAG가 필수는 아니다. 모든 단계에 RAG를 적용하면 불필요한 검색 비용이 발생하고, 엑셀 검증처럼 규칙 기반 처리가 필요한 기능까지 LLM 판단에 의존하게 된다.                                         | **리서치:** RAG가 필요한 상황과 필요하지 않은 상황을 기능별로 분리하였다. **적용:** RAG는 작성 항목의 의미가 불명확하거나, 컬럼 입력 규칙, 코드값 기준, 날짜 형식 기준, 기존 안내문 톤이 필요한 경우에만 호출한다. 단순 메일 요약, 제출 현황 계산, 엑셀 검증, 엑셀 병합에는 RAG를 사용하지 않는다.                                                                                                                                                 |
| **RAG 검색 품질 기준**          | RAG를 적용하더라도 검색된 문서가 실제 업무 기준과 관련이 낮으면 잘못된 안내문이 생성될 수 있다. 따라서 검색 결과의 신뢰도를 판단할 기준이 필요했다.                                                                                        | **리서치:** Vector 검색 결과의 score와 문서 유형 metadata를 함께 활용하는 방식을 검토하였다. **적용:** 현재 PoC는 `docs/reference` 키워드 검색과 `confidence_score` 반환까지만 구현하고, FAISS/Embedding/문서 metadata 필터링은 운영 확장 과제로 분리하였다.                                                                                |
| **엑셀 검증 정확도**             | 엑셀 데이터 검증은 동일한 입력에 대해 항상 동일한 결과가 나와야 한다. 필수값 누락, 날짜 형식 오류, 중복 데이터 같은 항목은 자연어 판단보다 명확한 규칙 기반 검증이 적합하다.                                                                         | **리서치:** pandas와 openpyxl 기반 엑셀 데이터 처리 방식을 검토하였다. **적용:** Excel Validation Agent는 LLM이 아니라 규칙 기반 로직으로 검증을 수행한다. 필수값 누락, 날짜 형식 오류, 코드값 오류, 중복 데이터를 각각 함수로 분리하고, 검증 결과는 오류 보고서로 생성한다. 원본 파일은 수정하지 않고 결과 파일만 별도로 저장한다.                                                                                                                  |
| **Agent 상태 관리**           | 취합 업무는 이전 단계의 결과가 다음 단계의 입력으로 사용된다. 예를 들어 메일 분석 결과는 작성 가이드 생성에 사용되고, 승인 상태는 메일 발송 여부를 결정하며, 검증 결과는 보고서 생성에 사용된다.                                                              | **리서치:** LangGraph의 State 기반 Workflow 설계를 검토하였다. **적용:** `AgentState`에 `request_id`, `gmail_message_id`, `extracted_requirements`, `reference_documents`, `approval_status`, `submission_status`, `validation_result`, `current_agent`, `langfuse_trace_id`를 저장하도록 설계하였다. Supervisor Agent는 이 상태값을 기준으로 다음 Agent를 선택한다.              |
| **출력 데이터 구조화**            | 메일 분석 결과나 엑셀 검증 결과가 자유 텍스트로만 반환되면 프론트엔드 표시, 후속 Agent 입력, 보고서 생성에 재사용하기 어렵다.                                                                                                   | **리서치:** Pydantic 모델과 JSON Output Parsing 방식을 검토하였다. **적용:** 메일 분석 결과, RAG 검색 결과, 제출 현황, 엑셀 검증 결과를 JSON 구조로 반환하도록 설계하였다. 예를 들어 `required_fields`, `deadline`, `missing_info`, `error_rows`, `duplicate_rows`, `submission_rate` 같은 필드를 고정하여 후속 단계에서 재사용할 수 있게 하였다.                                                                   |
| **모니터링 및 디버깅**            | 멀티 에이전트 구조에서는 Supervisor Agent가 어떤 기준으로 다음 Agent를 선택했는지, 각 Agent가 어떤 입력과 출력으로 실행되었는지 확인할 수 있어야 한다. | **리서치:** Langfuse 기반 LLM Observability와 Trace 관리 방식을 검토하였다. **적용:** 현재 PoC는 Console/File Log, `agent_handoff_history`, `reasoning_log`로 실행 흐름을 확인한다. Langfuse 정식 Trace는 환경 변수와 운영 계정이 준비된 후 확장 가능하도록 설정 구조만 분리하였다.                                   |
| **보안 및 민감정보 처리**          | 메일 본문, 첨부파일, 작성자 이메일, 엑셀 데이터에는 업무상 민감 정보가 포함될 수 있다. 전체 원문을 로그에 그대로 남기면 보안상 문제가 된다.                                                                                     | **리서치:** 로그 최소화와 민감정보 마스킹 기준을 검토하였다. **적용:** 현재 PoC의 Console/File Log에는 원문 전체가 아니라 request_id, 실행 단계, 오류 수, 요약 정보 중심으로 기록한다. 이메일 주소, 이름, 첨부파일 원문 데이터는 필요한 범위에서만 사용하고 운영 Trace 연동은 후속 확장 시 마스킹 정책과 함께 적용한다.                                                                                                                              |

***

### 핵심 동작 검증

위에서 구현한 기능이 의도대로 동작하는지 확인하기 위해 대표 시나리오를 기준으로 검증하였다.

**[검증 시나리오: 샘플 취합 요청 메일 분석 후 작성 가이드 생성 및 엑셀 검증]**

* **입력:**\
  "2026년 6월 시스템 개선 요청사항 취합 메일 본문을 분석해서 작성자용 가이드를 만들고, 업로드된 엑셀 파일을 검증해줘."

* **에이전트 동작:**

  1. Supervisor Agent가 사용자 요청을 분석한다.\
     → 현재 작업을 `취합 요청 메일 분석 및 제출 파일 검증` 업무로 분류한다.

  2. 사용자가 화면 또는 샘플 파일에서 메일 제목/본문과 엑셀 파일을 입력한다.\
     → 결과: 요청 메일 텍스트와 제출 파일 목록 확보

  3. Supervisor Agent가 Requirement Analysis Agent를 호출한다.\
     → `analyze_collection_email()` 실행\
     → 결과: 요청 목적, 작성 항목, 제출 기한 추출

  4. Supervisor Agent가 ToT 기반 검증 규칙 후보를 생성한다.\
     → Strict/Balanced/Loose 후보 비교\
     → 결과: 실제 업로드 컬럼과 가장 잘 맞는 규칙 선택

  5. Guide Draft Tool이 작성자용 가이드와 메일 초안을 생성한다.\
     → 실제 발송 전에는 사용자 승인 필요

  6. Submission Tracking Tool이 샘플 작성자 목록과 제출 식별자를 대조한다.\
     → 결과: 제출자, 미제출자, 지연 제출자 분류

  7. Supervisor Agent가 Excel Validation Agent를 호출한다.\
      → `validate_excel_data()` 실행\
      → 결과: 필수값 누락 2건, 날짜 형식 오류 1건, 중복 데이터 1건 탐지

  8. Self-Correction Agent가 안전한 오류만 자동 교정한다.\
      → 날짜 형식/코드값 정규화 후 재검증\
      → 결과: 개선된 경우만 채택

  9. Excel Validation Agent가 정상 데이터를 병합한다.\
      → `merge_excel_files()` 실행\
      → 결과: 최종 병합 파일 생성

  10. Supervisor Agent가 Report Agent를 호출한다.\
      → `generate_result_report()` 실행\
      → 결과: 제출 현황, 오류 내역, 병합 결과 보고서 생성

  11. 실행 로그가 기록된다.\
      → Supervisor Routing, Agent Handoff, ToT 선택, Self-Correction, Excel 검증 결과 기록

* **최종 결과:**

```text
요약:
2026년 6월 시스템 개선 요청사항 취합 메일을 분석하고 작성자용 작성 가이드를 생성했습니다.

상세 결과:
- 제출 기한: 2026-06-12 17:00
- 작성 항목: 부서명, 담당자, 요청 시스템, 개선 요청 내용, 긴급도, 요청 사유
- RAG 참고 문서: 1차 PoC에서는 핵심 경로에 미사용, 로컬 키워드 검색 Tool만 제공
- 제출 현황: 샘플 작성자 4명 중 제출 3명, 미제출 1명
- 엑셀 검증 결과: 필수값 누락 2건, 날짜 형식 오류 1건, 중복 데이터 1건
- 생성 파일: 오류 보고서, 최종 병합 파일, 결과 보고서

확인 필요 사항:
- 미제출자 2명에게 리마인드 메일 발송 여부 확인 필요
- 오류 데이터 4건에 대한 작성자 재제출 요청 여부 확인 필요

다음 조치:
1. 사용자가 메일 발송을 승인하면 mock 또는 Gmail API 발송 Adapter를 통해 초안을 발송할 수 있습니다.
2. 오류 데이터 수정본이 제출되면 Excel Validation Agent가 재검증을 수행합니다.
3. 모든 파일이 검증 완료되면 Report Agent가 최종 보고서를 갱신합니다.

실행 추적 정보:
- 현재 실행 구조: Multi-Agent Workflow
- 실행 Agent: Supervisor Agent, Requirement Analysis Agent, Excel Validation Agent, Self-Correction Agent, Report Agent
- 실행 로그: request_id, agent_handoff_history, reasoning_log
```
