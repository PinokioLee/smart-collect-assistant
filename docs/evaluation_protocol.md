# Smart Collect 정량 평가 프로토콜

## 목적

발표용 수치를 임의 가정하지 않고 다음 세 질문을 재현 가능한 방식으로 측정한다.

1. 키워드 규칙보다 LLM 분류가 다양한 업무 표현을 더 정확히 이해하는가?
2. 같은 Worker를 사용하더라도 Observation Loop가 있는 Agentic Graph가 고정 흐름보다 예외를 더 안전하게 처리하는가?
3. 사람이 동일 업무를 수행할 때보다 실제 E2E Agent 실행이 얼마나 시간을 줄이는가?

## 12개 통제 시나리오

일반, 스팸, 첨부 양식 요청, 신규 양식 요청, 정상 제출, 오류 제출, 질문, 연장,
작업번호 없는 제출, 수정본, 프롬프트 인젝션, 마감 리마인드를 사용한다.

`backend.smart_collect.benchmark_roi`는 각 시나리오마다 다음을 새로 만든다.

- 격리된 임시 SQLite DB
- 실제 `.xlsx` 입력 파일
- 필요한 Collection Job과 검증 규칙
- 동일한 Mock 발송 안전 설정

그 뒤 다음 실제 코드 경로를 실행한다.

- Rule Sequential: 휴리스틱 분류와 초기 요청 처리 경로
- Fixed Workflow: LLM/휴리스틱 분류와 동일 Worker를 사용하되 실패 Observation 재계획 없음
- Agentic Supervisor Graph: LangGraph, Worker, Observation, Human Review, Deadline Agent 전체 경로

결과 JSON의 `execution_mode=actual_code_path`, 시나리오별 `final_status`,
`trace_steps`, `e2e_latency_ms`가 실제 실행 증거다.

## 실행

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi --use-llm --output data\roi_benchmark_llm.json
```

`--use-llm`은 Fixed와 Agentic 경로에서 실제 Azure OpenAI 호출을 사용한다. Rule 기준선은
항상 휴리스틱을 사용한다. 실제 메일은 보내지 않으며 자동발송을 강제로 끈다.

## 의미 분류 기술 비교

E2E 시나리오와 별개로 우회 표현과 문맥 의존 표현을 포함한 24개 고정 평가셋에서
휴리스틱과 실제 Azure LLM의 상위 분류 및 세부 의도 일치율을 비교한다.

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_classifier --use-llm `
  --output data\classifier_benchmark.json
```

결과의 `actual_llm_responses`가 24여야 LLM 실측으로 인정한다. 이 데이터는 프로젝트
내부 평가셋이므로, 운영 전에는 비식별화한 실제 사내 메일로 블라인드 재평가한다.

## 사람 Before 실측

최소 3회, 가능하면 2명 이상이 동일한 12개 시나리오를 수작업으로 처리한다.

```powershell
.\.venv\Scripts\python.exe scripts\manual_roi_timer.py --participant P01
```

측정 범위는 메일 확인, 파일 열기, 규칙 검증, 반려 또는 승인 판단까지의 능동 작업시간이다.
대기·휴식시간은 제외한다. 측정이 끝나면 다음 명령으로 동일 시나리오 수 기준 ROI를 계산한다.

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi `
  --use-llm `
  --manual-csv data\manual_time_measurements.csv `
  --output data\roi_benchmark_llm.json
```

사람 실측 CSV가 비어 있으면 `roi_claim_available=false`이며 시간 절감률을 주장하지 않는다.

## 해석 제한

- 통제 데이터는 운영 메일 분포 전체를 대표하지 않는다.
- LLM 정확도는 모델 버전과 프롬프트 변경 시 다시 측정한다.
- 100%는 12개 시나리오 내부 성공률이지 일반적인 무오류 보장이 아니다.
- 운영 전에는 사내 조직도, 권한, 감사, 장애복구, 메일 보존 정책을 별도로 검증한다.
