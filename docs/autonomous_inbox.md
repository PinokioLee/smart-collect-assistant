# Autonomous Inbox Agent

## 실행 흐름

```text
APScheduler / 지금 실행
  → Gmail Intake Agent (최근 7일, 최대 100건, message-id 중복 방지)
  → LLM 계층형 분류
      일반메일 / 취합업무메일 / 스팸·위험메일
      취합업무: request / submission / question / correction / extension
  → LangGraph Supervisor
      모든 Worker capability 중 다음 행동 선택
      Route/Intent Policy Gate로 부적합한 실행 차단
  → 선택된 Worker
      Request: 양식 결정 → 요구분석/RAG → 요청메일
      Submission/Correction: 검증 → 반려 또는 병합
      Question: Job 사실 기반 답변
      Extension: Human Approval
  → 발송 Policy Gate → Gmail Send Tool 또는 검토 큐
  → Worker 결과 Observation
      성공: 종료
      실패: Supervisor 재계획 → 일시 오류 1회 재시도 → 구조적 실패/재실패 Human handoff
```

## 자동 발송 정책

LLM의 `simple` 판단만으로 발송하지 않는다. 다음 조건을 모두 만족해야 한다.

- 취합업무메일 중 `request` 의도
- 분류 신뢰도가 `AUTO_SEND_MIN_CONFIDENCE` 이상
- 마감일과 작성 항목이 명확하고 `missing_info`가 없음
- 메일에 대상 부서가 명시되면 조직도, 없으면 원본 From+Cc를 수신자로 사용
- 모든 수신자 도메인이 `AUTO_SEND_ALLOWED_DOMAINS`에 포함
- RAG/요구사항 근거 플래그 없음
- 실제 재첨부 가능한 양식 파일 존재
- 프롬프트 인젝션 등 위험 플래그 없음
- LLM Supervisor가 단순 업무이며 사람 확인이 불필요하다고 판단
- `AUTO_SEND_ENABLED=true`

하나라도 실패하면 메일은 발송되지 않고 승인 큐로 이동한다. 스팸·위험메일은
삭제하지 않고 격리한다.

## 환경 설정

```dotenv
EMAIL_READ_MODE=gmail
EMAIL_SEND_MODE=mock
AUTO_SEND_ENABLED=false
AUTO_SEND_MIN_CONFIDENCE=0.90
AUTO_SEND_ALLOWED_DOMAINS=company.com
```

개발·영상 리허설은 `EMAIL_SEND_MODE=mock`을 사용한다. 실제 발송 리허설은 별도
테스트 계정과 제한된 도메인으로 검증한 후 `gmail`로 변경한다.

## 감사 가능한 기록

SQLite의 각 메일 레코드에 다음을 보존한다.

- 상위 분류, 세부 의도, 신뢰도, LLM/Rule 출처
- 위험 플래그와 판단 근거
- 양식 선택 전략과 생성된 template_id
- Supervisor action과 정책 차단 사유
- 발송 결과 message_id

이 기록은 발표 시 `LLM 판단 → 정책 검증 → Tool Call` 로그로 사용할 수 있다.

## Worker Agent와 실제 행동

- Template/Communication Agent: 신규 취합 요청, 양식 선택·생성, Job ID 발급
- Validation Agent: 제출/수정본 Excel을 Job 검증 계약으로 검사
- Communication Agent: 검증 오류를 행·컬럼 단위 반려메일로 작성
- Q&A RAG Agent: Job의 마감·작성항목·양식 사실에 근거한 답변
- Deadline Agent: 연장 요청은 사람 승인, 마감 임박 미제출자는 리마인드
- Merge Agent: 전원 정상 제출 시 유효 행을 자동 병합
- Security Agent: 스팸·피싱·프롬프트 인젝션 격리

Collection Job 제목에는 `[SC-...]` 작업번호가 들어가므로 제출·질문·수정본을
원래 취합 건과 연결한다. 작업번호가 없고 활성 Job도 하나로 확정되지 않으면
임의 연결하지 않고 Supervisor가 사람 확인으로 재계획한다.

## 정량 비교

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi --use-llm `
  --output data\roi_benchmark_llm.json
```

이 명령은 임의 행동표가 아니라 시나리오별 임시 DB·Excel·Job을 만들고 실제
Rule/Fixed/Agentic 코드 경로를 실행한다. 결과의 `execution_mode=actual_code_path`,
`trace_steps`, `final_status`로 실행 여부를 확인할 수 있다.

수작업 ROI는 `scripts/manual_roi_timer.py`로 최소 3회 직접 측정한 뒤
`--manual-csv`로 전달한 경우에만 계산한다. 상세 절차는
`docs/evaluation_protocol.md`를 따른다.
