PoC 모듈 구현
최종 구현 기준 핵심 모듈, 동작 원리 및 기술 선택


### 핵심 구현 내용

초기 PoC의 메일 분석·Excel 검증·병합 기능을 실제 Gmail 이벤트 기반 멀티 에이전트로 확장하였다. 최종 구현은 “화면에 메일을 붙여 넣고 한 번 실행하는 도구”가 아니라, 메일 도착을 감지하고 업무 문맥에 따라 요청·질문·제출·수정·연장 처리를 이어가는 서비스다.

#### 1.1 이벤트 기반 멀티 에이전트 워크플로우

* 구현 위치: `backend/smart_collect/autonomous_graph.py`
* 운영 진입점: `run_mail_event()`
* 비교 실험 진입점: `run_fixed_mail_event()`

```text
START → Intake → Supervisor
                    ├─ General Mail Agent → END
                    ├─ Security Agent → END
                    ├─ Request Worker ─────┐
                    ├─ Submission Worker ──┤
                    ├─ Q&A Worker ─────────┤→ Observation
                    ├─ Extension Worker ───┘     ├─ 성공 → END
                    └─ Human Review → END        └─ 실패 → Supervisor 재계획
```

Supervisor는 메일 의도를 단순 `if/else`로 바꾸는 역할에 그치지 않는다. 현재 분류, 신뢰도, 첨부, 이전 Worker 결과, 실패 observation을 함께 받아 다음 행동을 JSON으로 선택한다. 실행 직전에는 코드 Policy Gate가 선택한 Worker와 메일 의도의 호환성을 다시 검사한다.

일시적 네트워크 오류는 한 번 재시도할 수 있지만 Job 미확인, 첨부 유실, 손상 파일 같은 구조적 실패는 재시도하지 않고 사람 확인으로 전환한다. 이 구조 덕분에 동일 Worker를 사용하는 14개 통제 시나리오에서 Fixed Workflow 78.57%, Agentic Supervisor 100%의 성공률을 기록했다. 반면 중앙 처리 지연은 약 2.67초에서 5.84초로 증가했다. 즉, 추가 판단 비용을 감수하고 오류 종료 대신 안전한 복구를 선택한 설계다.

#### 1.2 Gmail 수집과 화면 스케줄 연동

* 구현 위치: `backend/smart_collect/tools/inbox_tools.py`, `backend/smart_collect/scheduler.py`, `backend/smart_collect/inbox_pipeline.py`

| 기능 | 구현 내용 |
| --- | --- |
| 자동 확인 | UI에서 활성화, 실행 시각 목록, 타임존을 저장하면 APScheduler가 동일 설정으로 실행 |
| 즉시 실행 | `/api/schedule/run-now`를 호출해 같은 처리 경로 즉시 실행 |
| Gmail 읽기 | 제목, 본문, From/To/Cc, threadId, 첨부를 InboxMessage로 변환 |
| 중복 방지 | Gmail message-id를 기준으로 이미 처리한 이벤트 제외 |
| 첨부 수집 | Excel 첨부를 로컬 안전 경로에 다운로드해 Worker에 전달 |
| 대화 유지 | 질문 자동답변 시 `threadId`, `In-Reply-To`, `References`를 사용해 같은 대화로 회신 |

백엔드 프로세스가 실행 중이어야 정기 확인이 동작한다. 저장된 스케줄은 `data/schedule_config.json`에 유지된다.

#### 1.3 메일 계층형 분류

* 구현 위치: `backend/smart_collect/tools/mail_classifier.py`

LLM은 다음 스키마로 결과를 반환한다.

```json
{
  "category": "general | collection | spam",
  "intent": "request | submission | question | correction | extension | other",
  "confidence": 0.0,
  "risk_flags": [],
  "reason": "판단 근거"
}
```

상위 분류는 사용자가 이해하기 쉬운 세 종류로 제한하고, 실제 행동이 필요한 취합 업무만 다섯 의도로 세분화하였다. 자유문장 메일의 우회 표현을 처리하기 위해 Azure OpenAI Structured Output을 사용하며, 장애 시에는 휴리스틱 폴백과 그 출처를 기록한다.

24개 고정 평가셋에서 상위 분류와 세부 의도의 동시 일치율은 휴리스틱 45.83%, 실제 Azure LLM 100%였다. 이 결과가 분류 단계에 LLM을 사용한 정량적 근거다.

#### 1.4 요구사항 추출과 양식 결정

* 구현 위치: `backend/smart_collect/tools/requirement_tools.py`, `template_tools.py`, `mail_decision.py`

Requirement Analysis Agent는 메일에서 다음을 구조화한다.

* 취합 목적
* 작성 항목
* 제출 기한
* 주의사항
* 누락 정보

Template Design Agent는 두 경로 중 하나를 선택한다.

| 조건 | 처리 | 기본 운영 결정 |
| --- | --- | --- |
| 정해진 첨부 Excel이 있음 | 원본 양식 재사용 | 다른 안전 조건까지 만족하면 자동 처리 가능 |
| 첨부 양식이 없음 | LLM이 TemplateSpec 설계 후 openpyxl로 생성 | 새 양식은 사람이 확인한 뒤 발송 |

TemplateSpec에는 컬럼명, 자료형, 필수 여부, 허용값, 날짜 형식, 예시, 중복 키가 포함된다. 하나의 스펙에서 배포용 Excel과 제출 검증 규칙을 함께 생성하므로 “보낸 양식”과 “검증 기준”이 달라지는 문제를 방지한다.

#### 1.5 수신자 결정과 자동발송

* 구현 위치: `backend/smart_collect/tools/directory_tools.py`, `mail_decision.py`, `email_tools.py`

수신자 결정 우선순위는 다음과 같다.

1. 메일 본문에 부서·대상자가 명시되면 조직도에서 해당 대상자를 조회한다.
2. 대상자가 명시되지 않으면 최초 취합 요청 메일의 발신자와 참조자 전체를 기본 수신자로 사용한다.
3. 사용자는 UI에서 추가 수신자를 수동으로 넣을 수 있다.
4. 조직도 파일이 지정됐지만 읽지 못하거나 명시 부서를 찾지 못하면 샘플 대상자로 대체하지 않고 승인을 요청한다.

자동발송은 LLM 판단과 코드 정책을 함께 통과해야 한다.

| 검사 | 차단 조건 |
| --- | --- |
| 분류 신뢰도 | 기준값 미만 |
| 요구사항 | 마감·필수 항목·첨부 등 핵심 정보 누락 |
| 수신자 | 주소 오류, 빈 목록, 허용 도메인 밖 |
| 첨부 | 실제 재첨부 가능한 양식 파일 없음 |
| 보안 | 스팸·피싱·프롬프트 인젝션 위험 |
| RAG | 생성 내용의 근거 부족 또는 불일치 |
| 운영 설정 | `AUTO_SEND_ENABLED=false` |

개발 기본값은 `EMAIL_SEND_MODE=mock`, `AUTO_SEND_ENABLED=false`다. 실제 Gmail 발송은 테스트 계정과 허용 도메인 검증 후 활성화한다.

#### 1.6 작성 가이드 및 메일 생성

* 구현 위치: `backend/smart_collect/tools/guide_tools.py`, `rag_tools.py`, `advanced_rag.py`

Communication Agent는 추출된 요구사항과 양식 정보를 바탕으로 다음을 생성한다.

* `[SC-...]` Job ID가 포함된 제목
* 작성 목적과 마감
* 컬럼별 작성 방법과 허용값
* 제출 방법
* 첨부 양식

사용자가 저장한 과거 발송 메일이 있으면 스타일 RAG로 인사말, 문장 길이, 마무리 표현을 참고한다. 생성 후에는 Advanced RAG 검증이 마감, 필드, 첨부, 수신자 등 핵심 주장이 원본 요구사항과 맞는지 확인하고, grounding flag가 있으면 자동발송을 차단한다.

#### 1.7 질문 자동응답

* 구현 위치: `backend/smart_collect/autonomous_graph.py`의 Q&A Worker

작성자의 질문은 Gmail thread 또는 `[SC-...]` Job ID로 원래 취합 건과 연결한다. Q&A Agent는 저장된 다음 사실만 사용한다.

* 제출 마감
* 작성 항목
* 필수 여부
* 날짜·숫자 형식
* 코드 허용값
* 작성 가이드

LLM은 답변과 함께 사용한 근거 키를 반환한다. 질문자가 취합 대상자인지, thread/Job이 맞는지, 답변이 저장된 사실로 뒷받침되는지 코드가 확인한다. 기한 연장, 양식 변경, 예외 승인, 대리 제출처럼 정책을 바꾸는 질문은 자동답변하지 않고 사람 승인으로 보낸다.

#### 1.8 Excel 검증과 검증 규칙 후보 선택

* 구현 위치: `backend/smart_collect/tools/excel_tools.py`, `tot_rules.py`

Validation Agent는 다음 오류를 결정적 규칙으로 검사한다.

* 필수 컬럼과 필수값 누락
* 날짜 형식 오류
* 숫자 형식 오류
* 허용되지 않은 코드값
* 지정 키 기준 중복

Job에 배포한 TemplateSpec이 있으면 그 검증 계약을 그대로 사용한다. 레거시·외부 양식처럼 계약이 없으면 세 종류의 규칙 후보를 만들고 실제 파일 컬럼 coverage와 penalty를 계산해 가장 안전한 후보를 선택한다. 후보 탐색은 규칙을 임의로 늘리기 위한 것이 아니라, 존재하지 않는 컬럼을 필수로 강제하는 오탐을 줄이기 위한 장치다.

8개 파일·130행·정답 오류 26건 비교에서 Direct LLM과 규칙 검증 모두 F1 1.0이었다. 평균 처리 시간은 LLM 3,933.7ms, 규칙 21.12ms로 규칙이 약 186배 빨랐다. 따라서 자연어 의미 판단에는 LLM, 셀 단위 검증에는 규칙 코드를 선택했다.

#### 1.9 안전한 Self-Correction

* 구현 위치: `backend/smart_collect/tools/self_correction.py`

Self-Correction은 오류를 임의로 메우는 기능이 아니다. 다음 순서로 안전한 정규화만 시도한다.

```text
검증 오류
  → LLM 또는 규칙이 날짜·코드값 교정 후보 제안
  → 코드가 날짜 형식·허용값 검증
  → 원본이 아닌 별도 메모리/파일에 적용
  → 전체 규칙 재검증
  → 오류 수 감소 시 채택 / 같거나 증가하면 원본 유지
```

필수값 누락, 자유서술 내용, 업무 의미 판단이 필요한 값은 자동으로 채우지 않는다. 교정 전후 값, 방식, 제안 주체, 근거, 게이트 통과 여부를 로그에 남긴다.

#### 1.10 제출 추적, 반려, 리마인드 및 병합

* 구현 위치: `backend/smart_collect/job_store.py`, `deadline_agent.py`, `submission_tools.py`

제출 회신은 Job에 연결한 뒤 정상, 오류/재제출 대기, 완료 상태로 관리한다.

* 오류가 남으면 검증 결과의 파일·행·컬럼·입력값·허용 기준을 근거로 반려 메일을 작성한다.
* 정상 제출은 제출자 목록에 등록한다.
* 마감 임박 시 `전체 수신자 - 정상 제출자`로 미제출자를 계산한다.
* 모든 대상자가 정상 제출하면 유효 행을 최종 Excel로 병합한다.
* 원본 제출 파일과 자동 교정 전 원본은 변경하지 않는다.

#### 1.11 최종 통합 검증 및 최초 요청자 회신

작성 요청 수신자와 최초 요청자·참조자를 Collection Job에 분리 저장한다. 예상 작성자 전원의 정상 제출이 확인되면 Final Validation Agent가 전체 파일을 다시 검사해 파일 간 중복까지 확인한다.

* 예상 작성자가 아닌 제출자는 완료 인원에 포함하지 않고 사람 확인으로 전환한다.
* 최종 오류가 있으면 병합·완료·팀장님 회신을 차단하고 해당 파일 제출자를 재작성 대상으로 변경한다.
* 최종 오류가 0건이면 병합본을 생성한다.
* Completion/Report Agent가 작성 대상 수, 정상 제출 수, 병합 행 수, 오류 0건을 근거로 완료 메일을 작성한다.
* 병합본을 첨부하고 최초 요청 메일의 발신자는 To, 원본 참조자는 Cc로 유지해 같은 Gmail thread에 회신한다.
* 자동발송 정책을 통과하지 못하면 승인 큐에서 제목·본문·수신자를 직접 수정한 뒤 발송한다.

#### 1.12 기준 Excel 공통 값 일괄 업데이트

* 구현 위치: `backend/smart_collect/tools/excel_tools.py`의 `sync_common_fields_from_reference()`
* API: `/api/sync-common-fields`

하나의 기준 Excel과 여러 대상 Excel에서 같은 키를 찾고, 지정한 공통 컬럼의 값을 대상 파일 전체에 반영한다. 업데이트 건수와 미일치 키를 반환하며 결과 파일은 원본과 별도로 생성한다. 이 기능은 초기 프로젝트의 핵심 Excel 자동화 기능을 최종 메일 기반 Agent에도 유지한 것이다.

#### 1.13 상태 저장과 관찰 가능성

* 구현 위치: `backend/smart_collect/job_store.py`, `observability.py`, `llm.py`

SQLite에는 Collection Job, Submission, Inbox record, Agent Action Log를 저장한다. Langfuse가 활성화되면 메일 이벤트 하나를 Trace로 열고, 그 안에 Supervisor와 Worker의 각 LLM 호출을 Generation으로 기록한다.

| 기록 항목 | 활용 목적 |
| --- | --- |
| prompt/messages, response | 판단 근거와 출력 품질 분석 |
| model, token usage | 모델·비용 관리 |
| latency | 병목 구간 확인 |
| error/status | LLM 장애와 폴백 분석 |
| event_id/job_id | 메일·업무 단위 전체 실행 연결 |
| Agent action/observation | Tool 실행과 재계획 증명 |

Langfuse가 꺼져 있거나 기록에 실패해도 실제 취합 업무는 중단되지 않는다.

#### 1.14 FastAPI와 React UI

* Backend: `backend/api.py`
* Frontend: `frontend/`

주요 화면 기능은 다음과 같다.

* 자동 확인 활성화, 시각, 타임존 저장
* `메일 확인` 즉시 실행
* 일반·자동 처리·승인 필요·격리 큐 확인
* 승인 전 수신자 추가·삭제·교체와 제목·본문 수정·발송
* 최종 취합본과 팀장님 회신 초안 확인·다운로드·발송
* Collection Job과 Agent Action Log 확인
* 신규 양식 생성 및 다운로드
* 제출 검증·병합·오류 보고서 다운로드
* 기준 Excel 공통 값 일괄 업데이트
* 과거 발송 스타일 메일 저장·업로드


### 주요 문제 해결 및 기술 리서치

| 이슈 | 문제 원인 | 검토한 대안 | 최종 해결 |
| --- | --- | --- | --- |
| LangGraph를 썼지만 고정 흐름처럼 보임 | 항상 같은 순서로 노드를 실행 | 단순 Python chain, 고정 LLM workflow | Supervisor가 capability 선택, Worker observation을 받아 재계획하는 Graph 구현 |
| LLM 분류 필요성이 불명확 | 키워드 규칙도 빠르고 간단함 | 휴리스틱 단독 | 우회 표현 24건 비교 후 exact match 45.83% vs 100% 근거로 LLM 선택 |
| LLM이 Excel까지 검증하면 느리고 위험 | 셀 단위 사실 판정에 생성형 모델 사용 | Direct LLM validation | 130행 비교 후 동일 F1, 약 186배 빠른 규칙 검증 선택 |
| 자동발송 오발송 위험 | LLM의 confidence만으로 외부 행동 결정 | 항상 수동 승인 | LLM 판단+수신자·도메인·첨부·근거·위험 코드 Gate의 혼합 방식 |
| 짧은 회신이 일반 메일로 분류됨 | “네, 수정했습니다”에 취합 키워드가 없음 | 본문 키워드 추가 | Gmail thread와 활성 Job이 정확히 연결될 때만 문맥 보강 |
| 질문 답변 환각 위험 | LLM이 업무 규칙을 추측할 수 있음 | 자유 답변 | Job 사실 검색, 근거 키 기록, 정책 변경 질문 승인 전환 |
| 자동 교정으로 원본 훼손 가능 | 수정 후보가 업무 의미를 바꿀 수 있음 | 모든 오류 자동 수정 | 날짜·코드값만 허용, 코드 게이트, 재검증, 개선 시에만 별도 파일 채택 |
| Worker 실패 시 전체 작업 중단 | 고정 Workflow는 예외 후 다음 행동 없음 | 무제한 retry | transient 1회 retry, 구조 실패·재실패는 Human Review |
| LLM 사용 증거 부족 | 최종 결과만 있고 호출 단위 정보 없음 | 파일 로그만 사용 | 이벤트 Trace + 호출별 Langfuse Generation 계측 |


### 핵심 동작 검증

#### 검증 시나리오

14개 E2E 시나리오를 실제 임시 SQLite DB, 실제 Excel 파일, 실제 Worker 코드 경로로 실행했다.

1. 일반 메일
2. 스팸 메일
3. 첨부 양식 취합 요청
4. 신규 양식 취합 요청
5. 정상 제출
6. 오류 제출
7. 작성 질문
8. 연장 요청
9. Job 없는 제출
10. 첨부 유실
11. 손상 Excel
12. 수정본
13. 프롬프트 인젝션
14. 마감 리마인드

#### 검증 결과

| 항목 | 결과 |
| --- | --- |
| 백엔드 회귀 테스트 | 148 passed, 경고 1건 |
| 프론트 production build | 성공 |
| 휴리스틱 메일 category+intent exact match | 45.83%, 24건 |
| Azure LLM exact match | 100%, 24/24 실제 응답 |
| Fixed LLM Workflow E2E 성공률 | 78.57%, 14건 |
| Agentic Supervisor E2E 성공률 | 100%, 14건 |
| 구조 실패 복구 | Fixed 0% → Agentic 100%, n=3 |
| E2E 중앙 처리 지연 | Fixed 2,669.13ms → Agentic 5,837.94ms |
| Agentic 자율 해결률 | 71.43%; 나머지 4건은 의도된 사람 확인 |
| Excel 규칙 검증 | F1 1.0, 평균 21.12ms |
| Direct LLM 검증 | F1 1.0, 평균 3,933.7ms |

100%는 프로젝트 내부 통제 평가셋 결과이며 운영 환경의 무오류를 뜻하지 않는다. E2E 벤치마크는 mock 발송·자동발송 OFF로 실행했기 때문에 `unsafe_decisions=0`도 실제 Gmail 사고율이 아니라 잘못된 허용 판단이 없었다는 뜻이다.


### 1.4 추가 구현 및 최종 고도화

초기 PoC 이후 다음 기능을 추가해 실제 취합 담당자의 업무 흐름으로 확장했다.

* Gmail 상시 수집과 UI 스케줄 연동
* 일반·취합·스팸 및 5개 취합 의도 분류
* Supervisor 자율 라우팅과 Observation Loop
* 첨부 양식 재사용·신규 양식 생성 및 검증 계약 라운드트립
* 원본 발신자+참조자 기본 수신자와 수동 추가
* 안전 정책을 통과한 Gmail 자동발송
* 과거 발송 스타일 RAG와 생성 초안 grounding 검증
* 작성자 질문의 동일 thread 자동답변
* 제출 검증, 사실 기반 반려, 수정본 재검증
* 제한적 Self-Correction과 결정적 재검증
* 제출자 등록, 미제출자 리마인드, 전원 완료 병합
* 전체 파일 최종 교차 검증과 최초 요청자 완료 회신
* 기준 Excel 기반 공통 값 일괄 업데이트
* SQLite Agent Action Log와 Langfuse 호출 단위 추적
* Rule/Fixed/Agentic, Heuristic/LLM, LLM/Rule 검증 비교 벤치마크

최종 PoC는 LLM을 많이 호출하는 것이 목표가 아니라, LLM이 필요한 판단에는 LLM을 사용하고 정확성·속도·안전이 중요한 실행에는 검증 가능한 Tool을 선택한 하이브리드 에이전트다.
