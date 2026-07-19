E2E 서비스 개발
최종 서비스 아키텍처, 구현 범위, 성과 및 운영 고려사항


## 1. 최종 아키텍처 요약

* **완성된 서비스:** Gmail에 들어온 메일을 정기 또는 즉시 확인하고, LLM이 업무 의미와 위험도를 판단한 뒤 여러 Worker Agent와 결정적 Tool을 조합해 취합 업무를 수행하는 이벤트 기반 멀티 에이전트다.
* **핵심 설계:** LLM은 비정형 메일의 분류, 요구사항·양식 설계, 다음 행동 선택, 안내·반려·질문 답변을 담당한다. Excel 검증, 수신자·발송 정책, 교정 채택, 병합은 재현 가능한 코드가 담당한다.
* **사용자 경험:** 사용자는 자동 확인을 켜두거나 `메일 확인`을 누른다. 시스템은 일반·자동 처리·승인 필요·격리를 구분하고, 단순 업무는 처리하며 위험하거나 불명확한 건만 사용자에게 확인을 요청한다.
* **최종 산출물:** 신규 취합 양식, 작성 가이드, 요청/반려/질문 답변/리마인드 메일, 제출 현황, 교정본, 최종 병합 Excel, 최초 요청자 완료 회신, 오류 보고서, 기준값 동기화 파일, Agent 실행 로그.


### 1-1. 최종 처리 흐름

```text
Gmail / APScheduler / UI 지금 실행
        ↓
Inbox Intake Agent
일반 메일 · 취합 업무 · 스팸/위험
요청 · 제출 · 질문 · 수정 · 연장
        ↓
LangGraph Supervisor Agent
현재 상태 + 신뢰도 + 위험 + 이전 Worker observation
        ↓
Route/Intent Policy Gate
        ↓
┌──────────────────────────────────────────────────────────────┐
│ Request Worker                                               │
│ 요구 분석 → 첨부 양식 재사용/신규 양식 생성 → 안내 메일      │
├──────────────────────────────────────────────────────────────┤
│ Submission/Correction Worker                                 │
│ Job 연결 → 규칙 검증 → 제한적 Self-Correction → 반려/병합    │
├──────────────────────────────────────────────────────────────┤
│ Q&A Worker                                                   │
│ Gmail thread/Job 연결 → 사실 검색 → 자동답변/승인             │
├──────────────────────────────────────────────────────────────┤
│ Deadline Worker                                              │
│ 미제출자 계산 → 리마인드 / 연장 요청 → 사람 승인              │
├──────────────────────────────────────────────────────────────┤
│ Security Agent                                               │
│ 스팸·피싱·프롬프트 인젝션 → 격리                              │
├──────────────────────────────────────────────────────────────┤
│ Final Validation + Completion/Report Agent                   │
│ 전원 제출 → 전체 교차 검증 → 병합 → 최초 요청자 완료 회신     │
└──────────────────────────────────────────────────────────────┘
        ↓
External Action Policy Gate
자동발송 또는 승인 대기
        ↓
Worker Observation
성공 종료 / 일시 오류 1회 재시도 / 구조 실패·재실패 사람 확인
        ↓
SQLite Job·Submission·Action Log + Langfuse Trace/Generation
```

고정 Workflow와의 가장 큰 차이는 실패를 끝 상태로 두지 않는다는 점이다. Worker 결과가 observation으로 Supervisor에 돌아가며, 일시 오류는 제한적으로 재시도하고 구조적 실패는 안전한 사람 확인 상태로 재계획한다.


### 1-2. 기술 스택 구성 및 활용 방식

| 기술 스택 | 실제 사용 방식 | 다른 대안과 비교한 선택 이유 |
| --- | --- | --- |
| Azure OpenAI Structured Output | 메일 분류, Supervisor route, 요구사항·양식 설계, 안내·반려·Q&A 생성 | 키워드 휴리스틱 대비 24건 exact match 45.83% → 100%. 다양한 표현과 문맥 판단에 필요 |
| LangGraph | Supervisor, Worker routing, observation loop, retry/handoff | 동일 Worker를 고정 호출한 방식 대비 14건 성공률 78.57% → 100%, 구조 실패 복구 0% → 100%. 중앙 지연은 2.67초 → 5.84초로 증가 |
| Gmail API | 새 메일·첨부 읽기, From/Cc/thread 수집, 동일 thread 답장, 실제 발송 Adapter | 수동 업로드로는 상시 자동화와 대화 연결을 구현할 수 없음 |
| APScheduler | UI에서 저장한 시각·타임존의 정기 확인과 즉시 실행 | OS별 스케줄러보다 애플리케이션 설정·상태와 통합하기 쉬움 |
| pandas/openpyxl | Excel 로드, 검증, 양식 생성, 병합, 오류 보고서, 기준값 동기화 | Direct LLM과 F1은 1.0으로 같고 평균 21.12ms vs 3,933.7ms로 약 186배 빠름 |
| SQLite | Collection Job, Submission, Inbox record, Agent Action Log | 로컬 E2E 범위에서 설치 없이 영속 상태와 재현 가능한 로그 제공 |
| Langfuse | 메일 이벤트 Trace, LLM 호출별 prompt/response/token/latency/error Generation | 단순 파일 로그보다 LLM이 어느 판단에 사용됐는지 직접 확인 가능 |
| FastAPI | Gmail/스케줄/Agent/Excel/다운로드 REST API | 파일 업로드와 구조화 응답, React 연결이 간결함 |
| React + TypeScript + Vite | 메일 처리 큐, 승인, 스케줄, Agent Job, 실행 이력, Excel 도구 UI | CLI보다 비개발자가 자동 처리와 사람 확인 경계를 이해하기 쉬움 |


### 1-3. 최종 구현 범위와 운영 전 확장 구분

| 구분 | 현재 구현 | 운영 전 추가 필요 |
| --- | --- | --- |
| 메일 수신 | Gmail API 새 메일·첨부 수집, message-id 중복 방지 | 회사 계정 OAuth 승인과 메일 보존 정책 검토 |
| 스케줄 | UI 활성화·시각·타임존 저장, APScheduler, 지금 실행 | 이중화, 장애 알림, 서버 재기동 운영 절차 |
| 메일 분류 | 일반·취합·스팸 + 요청·제출·질문·수정·연장 | 비식별 실제 사내 메일 블라인드 재평가 |
| 취합 요청 | 요구 추출, 기존 양식 재사용, 신규 양식 생성 | 복잡한 다중 시트·매크로 양식 Parser 확대 |
| 역할·수신자 | 작성자와 최초 요청자·참조자 분리 저장, 승인 화면에서 추가·삭제·교체 | 실제 조직도·권한 시스템 연동 |
| 발송 | mock/Gmail Adapter, 정책 기반 자동발송·승인 | 테스트 계정과 제한 도메인 운영 리허설 |
| 질문 | thread/Job 기반 단순 질문 자동답변 | 내부 규정 문서 권한별 RAG와 답변 품질 운영평가 |
| 제출 | 검증, 제한적 교정, 반려, 수정본, 완료 등록 | 대용량·암호화·비표준 파일 처리 확대 |
| 최종 완료 | 예상 작성자 집합 확인, 전체 교차 검증, 병합본을 최초 요청자 thread로 회신 | 결재·전자문서 완료 보고 연동 |
| 마감 | 미제출자 계산, 리마인드, 연장 승인 | 휴일·조직별 알림 정책 연동 |
| Excel | 검증·병합·오류 보고서·기준값 일괄 동기화 | 업무별 검증 계약 템플릿 확장 |
| 관찰 | SQLite Action Log, Langfuse LLM trace | 민감정보 마스킹, 보존 기간, 접근 통제 |
| 인증 | 로컬 사용자 기준 | SSO, RBAC, 감사 승인 |


### 1-4. 초기 PoC 이후 고도화 내역

| 초기 상태 | 최종 고도화 |
| --- | --- |
| 사용자가 메일 내용을 화면에 입력 | Gmail 수신함 정기 확인과 즉시 실행 |
| 취합 요청 한 종류만 처리 | 일반·취합·스팸 및 취합 5개 의도 분류 |
| 고정된 순서로 분석→검증→병합 | Supervisor가 상황별 Worker 선택 |
| Worker 실패 시 오류 종료 | Observation Loop, 일시 오류 재시도, 구조 실패 사람 확인 |
| 양식이 주어진 파일만 검증 | 첨부 재사용 또는 자연어 기반 신규 양식 생성 |
| 수신자 수동 입력 | 명시 대상자 또는 원본 From+Cc 기본값, 수동 추가 |
| 승인 후 mock 발송 | 안전 정책을 통과한 Gmail 자동발송 가능 |
| 작성자 질문은 사람이 답변 | thread/Job grounding 기반 단순 질문 자동응답 |
| 오류 목록만 표시 | 사실 기반 반려 메일, 수정본 재검증 |
| 모든 오류는 사람이 수정 | 날짜·코드값만 제한적 Self-Correction 후 재검증 |
| 제출 파일 병합 중심 | 제출 추적·미제출 리마인드·완료 병합까지 연결 |
| 병합 후 사용자가 직접 결과 보고 | Final Validation + Completion/Report Agent가 팀장님 완료 회신까지 연결 |
| 공통값 수정 기능이 별도 | 기준 Excel 공통값 일괄 업데이트를 UI/API에 유지 |
| 로컬 로그 중심 | SQLite Action Log + Langfuse 호출 단위 추적 |
| 효과 설명이 추정 중심 | 24건·14건·130행 실제 코드 벤치마크 제공 |


## 2. KPI 달성도 (Plan vs Actual)

### 2-1. 실제 측정 KPI

| 평가 항목 | 비교 설계 | 실제 결과 | 판정 |
| --- | --- | --- | --- |
| 메일 의미 분류 | 휴리스틱 vs 실제 Azure LLM, 24건 | category+intent exact match 45.83% vs 100% | LLM 선택 근거 확보 |
| Agentic E2E 성공률 | 동일 Worker의 Fixed vs Agentic, 14건 | 78.57% vs 100%, +21.43%p | Observation Loop 효과 확인 |
| 구조 실패 복구 | Job 없음·첨부 유실·손상 Excel, n=3 | 0% vs 100% | 오류 종료를 안전한 Human Review로 전환 |
| 자율 해결률 | Agentic 14건 | 71.43% | 나머지 4건은 의도된 사람 확인 |
| E2E 중앙 처리 지연 | Fixed vs Agentic, 14건 | 2,669.13ms vs 5,837.94ms | 안전한 판단·복구를 위해 약 3.17초 증가 |
| Excel 오류 검출 | LLM vs 규칙, 8파일·130행·오류 26건 | 둘 다 Precision/Recall/F1 1.0 | 정확도 동률 |
| Excel 검증 속도 | 같은 데이터 | 3,933.7ms vs 21.12ms | 규칙이 약 186배 빠름 |
| 회귀 테스트 | 전체 Backend | 148 passed, 경고 1건 | 통과 |
| Frontend | production build | 80 modules transformed, build 성공 | 통과 |

### 2-2. 아직 확정하지 않은 KPI

| 항목 | 현재 상태 | 확정 방법 |
| --- | --- | --- |
| 사람 대비 시간 절감률 | 수작업 스톱워치 실측 없음 | 동일 14개 시나리오 최소 3회, 가능하면 2명 이상 측정 |
| 연간 절감 시간 | 운영 빈도·인원 데이터 없음 | 실제 월간 처리 건수와 유효 시간 실측으로 계산 |
| 실제 오발송률 | 벤치마크는 mock·자동발송 OFF | 테스트 계정과 제한 도메인 운영 리허설 후 측정 |
| 운영 메일 분류 정확도 | 내부 고정 평가셋만 측정 | 비식별 실제 사내 메일 블라인드 평가 |

사람의 Before 시간은 추정값을 실측값처럼 사용하지 않는다. `scripts/manual_roi_timer.py`로 유효 측정을 3회 이상 확보한 경우에만 ROI를 계산하도록 구현했다.


## 3. 창출된 핵심 가치

### 3-1. 비즈니스 가치

* **전수 수동 처리에서 예외 중심 관리로 전환**
  일반·스팸·단순 취합 건은 자동 분류하고, 불명확·정책 변경·구조 실패 건만 사람에게 보여준다.

* **메일과 Excel 사이의 끊어진 업무 연결**
  요청, 질문, 제출, 수정본, 리마인드, 병합을 Gmail thread와 Collection Job으로 연결해 담당자의 수동 대조를 줄인다.

* **작성자 질문과 오류 반려의 반복 감소**
  원래 요청의 사실에 근거한 답변과 행·컬럼 단위 오류 안내를 생성해 작성자가 무엇을 수정해야 하는지 바로 알 수 있다.

* **공통값 반복 수정 자동화**
  하나의 기준 Excel 값을 같은 키를 가진 여러 대상 파일에 일괄 반영하고 원본은 보존한다.

* **안전한 자동화 범위 확대**
  모든 건을 승인받는 방식보다 자동화 효과가 크고, 모든 건을 자동발송하는 방식보다 운영 위험이 낮다.


### 3-2. 기술적 가치

* **LLM과 결정적 코드의 역할을 측정으로 분리**
  의미 분류는 LLM이 우수했고 Excel 검증은 규칙이 같은 정확도에서 약 186배 빨랐다. 기술 선택이 선호가 아니라 비교 결과에 기반한다.

* **실질적인 Agentic 구조**
  Supervisor가 현재 상태와 실패 observation을 보고 Worker를 선택한다. Agentic 효과는 동일 capability Fixed Workflow와 직접 비교했다. 중앙 지연은 늘었지만 메일 비동기 업무에서 더 중요한 실패 복구와 안전한 사람 전환을 확보했다.

* **생성 양식과 검증 규칙의 단일 출처**
  TemplateSpec에서 배포용 Excel과 ValidationRule을 함께 만들어 작성 기준과 검증 기준의 불일치를 줄였다.

* **안전한 Self-Correction**
  LLM 제안을 그대로 적용하지 않고 코드 게이트와 재검증을 거쳐 오류가 감소한 경우에만 별도 교정본을 채택한다.

* **행동 전후의 이중 안전장치**
  Supervisor의 route는 Route/Intent Gate가, 메일 발송은 Recipient/Domain/Grounding Gate가 검증한다.

* **관찰 가능한 AI**
  SQLite에는 업무 행동을, Langfuse에는 LLM 호출 입력·출력·토큰·지연·오류를 남겨 문제 원인을 추적할 수 있다.


### 3-3. 사용자 가치

* 자동 확인과 `지금 실행` 중 상황에 맞는 시작 방식을 선택할 수 있다.
* 메일은 일반, 자동 처리, 승인 필요, 격리 상태로 쉽게 구분된다.
* 신규 양식이나 위험 요소가 있는 건만 검토하면 된다.
* 기본 수신자는 시스템이 구성하고 필요한 사람만 추가할 수 있다.
* Agent가 왜 자동발송하지 않았는지 위험 사유와 Action Log로 확인할 수 있다.
* 결과 Excel과 오류 보고서를 화면에서 바로 내려받을 수 있다.


## 4. 운영 및 보안 고려 사항

| 영역 | 현재 안전장치 | 운영 전 보완 |
| --- | --- | --- |
| 메일 발송 | mock 기본값, AUTO_SEND OFF, 허용 도메인, 신뢰도·첨부·수신자 Gate | 테스트 계정 리허설, 발송 한도, 취소·승인 감사 |
| 메일 읽기 | Gmail OAuth token, 중복 방지 | 최소 권한 scope, token 암호화·회수 정책 |
| 개인정보 | 로컬 SQLite·파일 저장 | 컬럼 마스킹, 암호화, 보존 기간, 삭제 정책 |
| 권한 | 로컬 단일 사용자 | SSO, 역할별 승인·다운로드 권한 |
| 조직도 | 파일 기반 CSV/JSON, 조회 실패 시 중단 | 사내 Directory API와 권한 동기화 |
| 프롬프트 공격 | 위험 분류, 스팸 격리, route/policy gate | 공격 패턴 회귀셋과 보안 모니터링 확대 |
| LLM 장애 | 휴리스틱 폴백, 제한적 retry, Human Review | circuit breaker, 장애 알림, 모델 failover |
| 관찰 도구 장애 | Langfuse 실패가 본 흐름에 영향 없음 | 민감정보 마스킹과 접근 통제 |
| Excel 원본 | 원본 미수정, 교정·동기화 결과 별도 저장 | 파일 무결성 hash와 문서 보존 연동 |


## 5. 회고 및 향후 확장

### 잘 해결한 점

* 멘토 피드백이었던 “LLM 활용이 얕고 Agentic하지 않다”는 문제를 기능과 비교 실험 양쪽에서 해결했다.
* Gmail 이벤트, Supervisor 판단, Worker Tool, observation 재계획을 연결해 고정 순차 파이프라인을 벗어났다.
* LLM이 잘하는 자연어 의미 판단과 코드가 잘하는 정확한 검증을 구분했다.
* 단순 질문은 자동화하면서 정책 변경은 사람에게 넘겨 실무 적용 가능성을 높였다.
* 초기의 Excel 병합·공통값 일괄 업데이트 기능을 최종 Agent 흐름에서 유지했다.
* 정량 수치를 실제 코드 경로와 JSON 증빙으로 남겼다.

### 기술적 한계

* 24건 분류, 14건 E2E, 130행 검증은 프로젝트 내부 통제 데이터이며 운영 분포 전체를 대표하지 않는다.
* 실제 사람의 수작업 시간 측정이 없어 시간 절감률과 연간 ROI는 아직 확정할 수 없다.
* 실제 Gmail 자동발송은 계정·허용 도메인 설정에 의존하며 기본값은 비활성화다.
* 복잡한 다중 시트, VBA, 병합 셀, 암호화 Excel은 완전 자동 처리 대상이 아니다.
* SQLite는 로컬·단일 인스턴스에는 적합하지만 다중 사용자 운영에는 외부 DB와 동시성 설계가 필요하다.
* 사내 SSO, RBAC, 데이터 마스킹, 보존 정책은 운영 전 추가해야 한다.

### Next Step

1. 비식별 실제 업무 메일 50건 이상으로 분류 블라인드 평가
2. 동일 14개 업무의 사람 수작업 시간 최소 3회 실측 및 ROI 계산
3. 제한된 테스트 계정·도메인에서 Gmail 자동발송 E2E 리허설
4. 실제 조직도 API와 SSO/RBAC 연동
5. 업무 유형별 TemplateSpec·검증 계약 카탈로그 확대
6. Langfuse 기반 분류 오류, fallback 비율, token, latency 운영 대시보드 구축
7. PostgreSQL·Object Storage로 상태와 파일 저장 확장
8. 회사 보안 정책에 맞춘 개인정보 마스킹·암호화·보존기간 적용


## 6. 최종 검증 및 산출물 근거

### 재현 명령

```powershell
cd D:\AI_MASTER\smart-collect-assistant
$env:PYTHONPATH='backend'

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m smart_collect.benchmark_classifier --use-llm
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi --use-llm

cd frontend
npm run build
```

### 근거 파일

| 근거 | 파일 |
| --- | --- |
| 프로젝트 개요와 실행법 | `README.md` |
| 이벤트 기반 Agent Graph | `backend/smart_collect/autonomous_graph.py` |
| Gmail 수집과 스케줄 | `backend/smart_collect/inbox_pipeline.py`, `scheduler.py`, `tools/inbox_tools.py` |
| 메일 분류 비교 | `data/classifier_benchmark.json` |
| Excel LLM/규칙 비교 | `data/llm_vs_rule_benchmark_large.json` |
| Fixed/Agentic E2E 비교 | `data/roi_benchmark_llm.json` |
| 평가 방법과 해석 제한 | `docs/evaluation_protocol.md` |
| 자율형 Inbox 상세 | `docs/autonomous_inbox.md` |
| 사람 Before 측정 | `scripts/manual_roi_timer.py` |

### 최종 검증 결과

* Backend: 148 passed, 경고 1건
* Frontend: production build 성공
* 분류: 휴리스틱 45.83% vs Azure LLM 100%, 24건
* Agentic: Fixed 78.57% vs Agentic 100%, 14건
* 실패 복구: 0% vs 100%, n=3
* E2E 중앙 지연: Fixed 2,669.13ms vs Agentic 5,837.94ms
* Excel: 두 방식 F1 1.0, 규칙 평균 21.12ms, LLM 평균 3,933.7ms

본 결과는 최종 코드와 내부 통제 평가셋에 대한 실제 실행 결과다. 사람 대비 시간 절감률과 운영 효과는 실측 데이터가 확보된 이후 별도로 확정한다.
