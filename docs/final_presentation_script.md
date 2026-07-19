# 최종 발표 스크립트 — 9분 40초

## 0:00–0:20 · 표지

Smart Collect는 Gmail에 들어온 취합 업무를 사람이 일일이 확인하지 않아도, LLM이 업무 맥락을 판단하고 적합한 Agent와 Tool을 선택해 끝까지 처리하는 시스템입니다. 이번 고도화의 핵심은 단순히 메일 문장을 생성하는 수준에서, 실패를 관찰하고 다음 행동을 바꾸는 자율형 멀티 에이전트로 전환한 것입니다.

## 0:20–2:10 · 프로젝트 개요

기존 업무는 메일 확인, 요구사항 해석, 양식 선택 또는 신규 생성, 대상자 발송, 제출본 검증, 오류 반려, 수정본 재검증, 미제출자 독촉까지 여러 수작업으로 나뉩니다. 기존 버전은 LangGraph를 사용했지만 실행 순서가 고정되어 질문, 수정본, 마감 연장, 작업 실패를 만나면 사람이 다시 개입해야 했습니다.

고도화 버전은 Gmail 스케줄 수집 후 LLM이 일반 메일, 취합 업무, 스팸 위험으로 1차 분류하고, 취합 업무는 요청, 제출, 질문, 수정본, 연장 요청의 5개 의도로 다시 분류합니다. Supervisor는 현재 상태에서 허용된 Worker를 선택합니다. Worker는 양식 재사용 또는 생성, 작성 안내 메일, 제출 검증과 반려, Q&A, 연장 승인, 리마인드, 최종 병합을 담당합니다.

의미 분류는 우회 표현을 포함한 24개 평가셋에서 휴리스틱이 45.8%, Live Azure LLM이 100%(의도 일치)였습니다. 동일 Worker·Deadline·Self-Correction을 가진 14개 비교에서는 Fixed LLM Workflow 78.6%, Agentic Supervisor Graph 100%였습니다. 구조 실패 3건의 안전 복구율은 0%에서 100%로 상승했습니다. 대신 Supervisor 재계획 비용으로 배치 시간은 79.95초에서 111.89초로 약 40% 증가했습니다. 사람 수동 처리 ROI는 아직 스톱워치 실측이 없어 주장하지 않습니다.

## 2:10–5:55 · 기술 아키텍처

입력은 Gmail과 APScheduler입니다. Intake Agent가 분류와 의도 분석을 하고, Supervisor LLM이 현재 상태와 이전 Worker의 observation을 보고 다음 Worker를 선택합니다. Request는 Template과 Communication, Submission과 Correction은 Validation 이후 Reject 또는 Merge, Question은 사실 기반 Q&A, Extension과 Deadline은 승인 또는 Reminder로 연결됩니다.

중요한 점은 Worker 실패가 종료가 아니라 observation으로 Supervisor에 돌아간다는 것입니다. timeout이나 rate limit 같은 일시 오류는 1회 재시도하고, 제출 메일에 작업번호가 없는 job_not_found 같은 구조적 실패나 재실패는 Human Review로 재계획합니다. 모든 단계는 Collection Job, Submission, Agent Action Log에 저장됩니다.

기술 선택도 역할별로 나눴습니다. 첫째, LangGraph Supervisor는 실패 이후 경로 변경과 상태 보존이 필요해 선택했습니다. 기능을 동일하게 맞춘 14개 시나리오에서 Fixed는 78.6%, Agentic은 100%였고, 작업번호 없음·첨부 경로 유실·손상 Excel의 복구율은 0%에서 100%로 개선됐습니다. 통제 차이는 Worker 실패 observation을 Supervisor에 되돌리는지뿐입니다. 대가는 약 40%의 배치 지연 증가입니다. 규칙 선택은 ToT 완전 구현이 아니라 그 탐색 패턴에서 착안한 Strict/Balanced/Loose 결정론 후보 비교이며, 교정은 LLM 제안 후 코드 재검증을 통과할 때만 채택합니다.

둘째, Azure OpenAI는 표현이 다양한 일반, 취합, 스팸과 5개 업무 의도를 함께 판단해야 하므로 사용했습니다. 24개 평가셋에서 휴리스틱 45.8% 대비 Live LLM 100%(의도 일치)였고, LLM 중앙 응답시간은 2.46초입니다. 이 지연은 구조화되지 않은 판단에만 지불합니다.

셋째, Excel 셀 검증과 발송 안전성은 LLM이 아니라 Rule Validator와 Policy Gate가 담당합니다. 130행·26오류 검증에서 LLM과 Rule 모두 F1 1.0이었지만 Rule은 21.12ms, Direct LLM은 3,934ms로 규칙이 약 186배 빨랐고 재현 편차는 0이었습니다. 따라서 LLM은 판단, 코드는 빠르고 재현 가능한 실행 검증에 배치했습니다.

## 5:55–9:20 · 핵심 기술 과제와 결과

가장 어려운 과제는 자율성과 안전성을 동시에 확보하는 것이었습니다. LLM에게 자유롭게 메일 발송 권한을 주면 잘못된 수신자, 근거 없는 답변, 불완전 양식 같은 사고 위험이 있습니다.

이를 위해 Supervisor 출력은 허용된 enum 행동으로 제한하고, 요청과 회신은 Job ID로 연결했습니다. confidence, 마감, 필수 필드, 첨부 파일, 허용 도메인, 답변 grounding을 코드 Gate가 검증합니다. 연장 요청이나 취합 Job을 찾지 못한 제출은 반드시 사람 승인을 받습니다. 모든 판단과 실행 결과는 Agent Action Log에 남습니다.

실제 실패 흐름은 Intake, Supervisor, Validation의 job_not_found, Observation, Supervisor 재계획, Human Review 순서입니다. 이것이 기존의 고정 파이프라인과 가장 큰 차이입니다.

결과는 14개 내부 시나리오 성공 100%, 구조 실패 복구 100%(3/3), 의미 분류 100%(24/24)입니다. `unsafe_decisions=0`은 mock·자동발송 OFF에서 잘못된 허용 결정이 없었다는 뜻이지 실제 Gmail 사고율이 아닙니다. 사람 대비 시간 절감은 아직 `roi_claim_available=false`이며, 최소 3회 스톱워치 측정이 끝난 뒤에만 계산합니다. 분석적 추정은 별도 파일에 격리하고 발표 KPI로 사용하지 않습니다.

## 9:20–9:40 · 마무리

Smart Collect의 핵심은 LLM이 다음 행동을 선택하고, 결정적 코드와 정책이 그 행동의 실행 가능 여부를 검증한다는 점입니다. 이를 통해 메일 취합 업무를 단순 자동화가 아니라 안전한 자율형 Agent 업무로 전환했습니다.
