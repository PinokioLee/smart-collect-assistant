# Smart Collect Assistant

Gmail에 들어온 메일을 지속적으로 확인하고, LLM이 업무 의미와 위험도를 판단한 뒤 여러 Worker Agent와 결정적 Tool을 조합해 취합 업무를 수행하는 이벤트 기반 멀티 에이전트입니다.

핵심은 “LLM이 모든 것을 처리한다”가 아닙니다. LLM은 구조화되지 않은 메일의 의미와 다음 행동을 판단하고, Excel 검증·수신자 정책·발송 허용 여부는 빠르고 재현 가능한 코드가 검증합니다.

## 자동 처리 흐름

```text
Gmail / APScheduler
        ↓
Inbox Intake Agent
일반 메일 · 취합 업무 · 스팸 위험
request · submission · question · correction · extension
        ↓
Supervisor LLM
현재 상태와 이전 Worker observation으로 다음 행동 선택
        ↓
Request → Template + Communication
Submission/Correction → Validation → Reject 또는 Merge
Question → Grounded Q&A
Extension/Deadline → Human Approval 또는 Reminder
        ↓
성공 종료 · 실패 재계획 · 위험 작업 사람 승인
```

요청과 회신은 `[SC-...]` Job ID로 연결됩니다. 모든 분류, 라우팅, Tool 실행, 실패, 재계획 결과는 SQLite의 Agent Action Log에 남습니다.

## 주요 기능

- Gmail 새 메일 스케줄 수집 및 화면의 `지금 실행` 트리거
- 일반 메일 / 취합 업무 / 스팸 위험의 3분류
- 취합 요청 / 제출 / 질문 / 수정본 / 연장 요청의 5개 업무 의도
- 첨부 양식 재사용 또는 요구사항 기반 Excel 양식 신규 생성
- 수신자·마감·필수 필드·grounding·도메인 정책 기반 자동발송/승인 분기
- 제출 Excel의 필수값, 날짜, 숫자, 코드값, 중복 검증
- 검증 실패 사실에 근거한 LLM 반려 메일 작성
- 수정본 재검증, 정상 제출 병합, 미제출자 리마인드
- 취합 대상자의 회신 질문을 원래 Gmail 대화와 Job에 연결해 근거 기반 자동답변
- 기한·양식 변경, 예외 승인, 비대상자 질문은 자동답변하지 않고 승인 큐로 전환
- Worker 실패 observation → 일시 오류 1회 재시도 → 구조적 실패/재실패 Human Review
- Agent Job과 실행 로그를 보여주는 React UI

## 안전 기본값

`.env.example`의 기본 의도는 실메일 오발송을 방지하는 것입니다.

```env
EMAIL_SEND_MODE=mock
AUTO_SEND_ENABLED=false
AUTO_SEND_ALLOWED_DOMAINS=
```

실제 Gmail 자동발송은 테스트 계정과 허용 도메인을 준비한 뒤에만 켜십시오. 연장 요청, 불명확한 취합 Job, 낮은 신뢰도, 정책 예외는 자동발송하지 않고 승인 대기로 보냅니다.

운영 수신자는 `DIRECTORY_FILE`에 `name,dept,email` 열을 가진 UTF-8 CSV 또는 같은
키의 JSON 배열을 지정합니다. 파일이 지정됐는데 읽지 못하거나 명시 부서를 찾지 못하면
내장 샘플이나 전 직원으로 폴백하지 않고 발송을 중단해 승인 대기로 보냅니다.

## 실행

### 백엔드

```powershell
cd D:\AI_MASTER\smart-collect-assistant
.\.venv\Scripts\Activate.ps1
python backend\api.py
```

FastAPI: `http://127.0.0.1:8000`

### 프론트엔드

```powershell
cd D:\AI_MASTER\smart-collect-assistant\frontend
npm install
npm run dev
```

React UI: `http://127.0.0.1:5173`

## 자동 수집 스케줄

UI에서 활성화 여부, 시각 목록, 타임존을 저장하면 백엔드 APScheduler가 같은 설정을 사용합니다. 현재 저장 예시는 `09:00, 14:00, 19:00 / Asia/Seoul`입니다. 백엔드 프로세스가 실행 중이어야 자동 확인이 동작합니다.

스케줄 실행 순서:

1. Gmail의 새 메일 수집
2. 이벤트 기반 Supervisor Graph 처리
3. 마감 임박 Job의 미제출자 계산
4. 리마인드 초안 또는 안전 정책을 통과한 발송

## 데모 데이터 준비

실제 Gmail을 읽거나 메일을 보내지 않고 Agentic 흐름을 UI에서 재현합니다.

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe scripts\prepare_agentic_demo.py
```

Azure LLM 호출 없이 빠르게 준비하려면 `--offline`을 추가합니다. 두 방식 모두 자동발송은 강제로 꺼집니다.

## 벤치마크

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi --use-llm
```

벤치마크는 각 시나리오마다 격리된 SQLite DB, 실제 Excel 파일, Collection Job을
준비한 뒤 세 아키텍처의 실제 코드 경로를 실행합니다. 결과 JSON에서
`evidence_level=actual_workflow_execution`, 시나리오별 `final_status`, `trace_steps`,
`e2e_latency_ms`를 확인할 수 있습니다.

의미 분류 기술 선택은 표현이 우회적인 별도 24개 평가셋으로 검증합니다.

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_classifier --use-llm
```

Excel의 날짜·숫자·필수값 검증에서는 규칙과 LLM의 F1이 같고 규칙이 훨씬 빠르므로
결정적 규칙을 선택했습니다. 반면 자유문장 의미 분류와 예외 라우팅에는 LLM을
사용합니다. 즉, LLM을 모든 단계에 쓰는 대신 측정 결과에 따라 역할을 나눴습니다.

2026-07-19 실제 실행 스냅샷:

| 기술 선택 질문 | 대안 | 선택 | 측정 결과 | 결론 |
|---|---:|---:|---|---|
| 의미·의도 분류 | 휴리스틱 45.83% | Azure LLM 100% | 24건 exact match, LLM 응답 24/24 | 문맥 해석은 LLM |
| Excel 오류 검증 | Direct LLM F1 1.0 / 3,933.7ms | 규칙 F1 1.0 / 21.12ms | 130행·오류 26건 | 검증은 결정적 규칙 |
| 업무 오케스트레이션 | Rule 41.67%, Fixed LLM 83.33% | Agentic 100% | 12건 E2E, unsafe 0건 | 예외·마감은 Supervisor Graph |

위 100%는 고정 평가셋 내부 결과이며 일반적인 무오류를 뜻하지 않습니다. 원본 결과는
`data/classifier_benchmark.json`, `data/llm_vs_rule_benchmark_large.json`,
`data/roi_benchmark_llm.json`에 보존합니다.

사람의 Before 시간은 임의로 가정하지 않습니다. 다음 도구로 최소 3회 측정한 경우에만
동일 시나리오 수로 정규화한 시간 절감률과 배수를 계산합니다.

```powershell
.\.venv\Scripts\python.exe scripts\manual_roi_timer.py --participant P01
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi --use-llm `
  --manual-csv data\manual_time_measurements.csv `
  --output data\roi_benchmark_llm.json
```

측정 범위와 한계는 `docs/evaluation_protocol.md`에 명시했습니다.

## 검증

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -q

cd frontend
npm run build
```

현재 기준은 위 명령으로 재검증하며, 테스트 수를 문서에 고정해 오래된 수치를 남기지 않습니다.

## 주요 파일

- `backend/smart_collect/autonomous_graph.py`: Supervisor + Worker + observation loop
- `backend/smart_collect/job_store.py`: Collection Job, Submission, Agent Action Log
- `backend/smart_collect/deadline_agent.py`: 마감 임박·미제출 리마인드
- `backend/smart_collect/benchmark_roi.py`: Rule / Fixed LLM / Agentic 비교
- `backend/smart_collect/benchmark_classifier.py`: 휴리스틱 / LLM 의미 분류 비교
- `scripts/manual_roi_timer.py`: 실제 수작업 Before 시간 측정
- `docs/evaluation_protocol.md`: 재현 가능한 정량 평가 절차와 해석 제한
- `backend/smart_collect/inbox_pipeline.py`: Gmail 수집과 이벤트 Graph 연결
- `backend/smart_collect/tools/advanced_rag.py`: 생성 초안의 사후 grounding 검증
- `scripts/prepare_agentic_demo.py`: 안전한 시연 데이터 생성
- `docs/autonomous_inbox.md`: 상세 아키텍처
