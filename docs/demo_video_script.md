# 시연 영상 대본 — 목표 4분 30초

## 녹화 전 안전 설정

1. `.env`에서 `EMAIL_SEND_MODE=mock`, `AUTO_SEND_ENABLED=false`를 유지한다.
2. `PYTHONPATH=backend .venv\Scripts\python.exe scripts\prepare_agentic_demo.py`로 실제 LangGraph 데모 데이터를 만든다.
3. 백엔드와 프론트엔드를 실행한다.
4. 화면에는 토큰, API 키, 실제 Gmail 주소가 보이지 않도록 한다.

## 0:00–0:35 · 자동 감시와 입력

- 자동 수집 스케줄이 화면에서 설정한 09:00, 14:00, 19:00(Asia/Seoul)로 저장되어 있음을 보여준다.
- `지금 실행` 버튼은 Gmail을 즉시 한 번 확인하는 수동 트리거라고 설명한다.
- 내레이션: “메일을 사람이 열어보는 대신, 저장된 스케줄마다 Inbox Intake Agent가 새 메일을 가져옵니다.”

## 0:35–1:25 · 취합 요청 → 양식 결정 → 발송 정책

- `DEMO-REQ` 카드를 연다.
- 일반/취합/스팸 3분류와 request 의도, 신뢰도, 신규 양식 생성 결과를 보여준다.
- `Agent 실행 로그`에서 Intake → Supervisor → Template/Communication 흐름을 보여준다.
- `사람 승인` 상태를 가리키며 자동발송 조건과 검토 조건을 설명한다.

## 1:25–2:15 · 잘못된 제출 → 자동 검증·반려

- `DEMO-BAD` 카드를 보여준다.
- 담당자 누락, 매출액 숫자 오류, 허용되지 않은 진행상태를 Rule Validator가 검출한 것을 보여준다.
- LLM이 검증 사실을 바꾸지 않고 자연스러운 반려 메일을 작성하며, 현재 안전 설정에서는 승인 대기함을 설명한다.

## 2:15–2:55 · 수정본 → 재검증

- `DEMO-CORRECT` 카드를 보여준다.
- correction 의도로 분류되고 같은 Job ID에 연결된 뒤 재검증을 통과한 상태를 보여준다.
- Job 카드에서 제출 상태 변화와 최종 병합 조건을 설명한다.

## 2:55–3:45 · 핵심 Agentic 장면: 실패 관찰과 재계획

- `DEMO-ORPHAN`의 Agent 로그를 확대한다.
- Intake → Supervisor → Validation `job_not_found` → Observation → Supervisor → Human Review 순서를 천천히 보여준다.
- 내레이션: “고정 파이프라인이라면 여기서 오류로 끝나지만, Supervisor는 실패를 observation으로 받아 다음 행동을 Human Review로 바꿉니다.”

## 3:45–4:10 · 스팸·프롬프트 인젝션 차단

- `DEMO-SPAM`의 quarantined 상태와 risk flag를 보여준다.
- 내레이션: “프롬프트 인젝션 가능성이 있는 메일은 어떤 Tool도 실행하지 않고 격리합니다.”

## 4:10–4:30 · 정량 결과와 한계

- 최종 발표자료의 14개 시나리오 결과를 10초간 보여준다.
- 내레이션: “동일 기능의 Fixed 대비 Agentic 업무 성공률은 78.6%에서 100%로 개선됐고, 구조적 실패 3건은 모두 안전하게 사람 검토로 전환했습니다. 자동 처리 성공률은 두 방식 모두 71.4%이며, 실제 사람 대비 시간 ROI는 아직 측정 전입니다.”

## 실제 Gmail 자동발송을 촬영할 때만

- 개인 계정이 아닌 시연용 Gmail 계정과 테스트 수신자 도메인을 사용한다.
- `EMAIL_SEND_MODE=gmail`, `AUTO_SEND_ENABLED=true`, `AUTO_SEND_ALLOWED_DOMAINS=<test-domain>`을 녹화 직전에 설정한다.
- 정상적이고 단순한 요청만 자동발송되며, 연장·불명확·정책 예외는 승인 대기인지 확인한다.
- 녹화 후 즉시 `EMAIL_SEND_MODE=mock`, `AUTO_SEND_ENABLED=false`로 되돌린다.
