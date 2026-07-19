# 사람 수동 처리 시간 — 분석적 추정 (ROI Before)

> ⚠️ 이 문서의 사람 시간은 **스톱워치 실측이 아니라 작업 분해 기반의 분석적 추정(analytical estimate)** 입니다.
> 이 값은 업무 계획 참고용이며 **최종 발표 KPI로 사용하지 않습니다.**
> 실측으로 대체하려면 `scripts/manual_roi_timer.py`로 최소 3회 측정 후
> `data/manual_time_measurements.csv`를 만들어 `benchmark_roi --manual-csv`에 넣으면 이 추정을 덮어씁니다.

## 추정 방법 (Analytical Estimating)

`docs/evaluation_protocol.md`의 14개 통제 시나리오를 사람이 직접 처리한다고 가정하고,
각 시나리오를 세부 작업으로 분해해 **능동 작업시간(active time)** 만 합산했다.
대기·회신 기다림·휴식은 제외한다. 시나리오별 시간이 편중되므로(예: 신규 양식 설계는 길고
스팸 식별은 짧음), 배치 정규화에는 **평균이 아니라 중앙값(median)** 을 써서 이상치 영향을 줄였다.

## 시나리오별 추정 (능동 작업시간, 분)

| # | 시나리오 | 사람이 하는 세부 작업 | 추정(분) |
|---|---|---|---:|
| 1 | 일반 메일 | 읽고 업무 아님 판단·아카이브 | 0.5 |
| 2 | 스팸/위험 | 발신·본문으로 스팸 식별·격리 | 0.5 |
| 3 | 첨부 양식 요청 | 양식 확인 → 대상자 추출 → 발송 메일 작성·발송 | 6.0 |
| 4 | 신규 양식 요청 | 요구 해석 → 컬럼 설계 → Excel 양식 제작 → 발송 | 12.0 |
| 5 | 정상 제출 | 파일 열기 → 행 검증 → 병합·기록 | 3.0 |
| 6 | 오류 제출 | 행별 검증 → 오류 판정 → 근거 기반 반려 메일 작성 | 6.0 |
| 7 | 질문 회신 | 원 요청 대조 → 근거 확인 → 답변 작성 | 4.0 |
| 8 | 마감 연장 요청 | 타당성 판단 → 승인/거절 라우팅 | 2.0 |
| 9 | 작업번호 없는 제출 | 어느 Collection Job인지 추적·대조 | 3.0 |
| 10 | 수정본 제출 | 이전 제출과 연결 → 재검증 → 병합 | 3.5 |
| 11 | 프롬프트 인젝션/악성 | 식별·차단·기록 | 1.0 |
| 12 | 마감 임박 리마인드 | 미제출자 계산 → 독촉 메일 작성 | 5.0 |
| 13 | 첨부 경로 유실 | 원 메일·첨부를 다시 확인하고 재요청 또는 담당자 확인 | 2.0 |
| 14 | 손상된 Excel | 파일 열기 실패 확인 → 재첨부 요청 작성 | 4.0 |

- 합계: **52.5분 / 14건**
- 중앙값: **3.25분/건 (195초)**, 범위 0.5~12.0분

## 산출 방법 (Agent 시간은 실측)

- 사람(추정, 정규화): 195초/건 × 12건 = **2,340초 ≈ 39분**
- Agent 시간은 최신 `roi_benchmark_llm.json`의 Agentic 배치 실측값을 사용합니다.
- `scripts/apply_roi_estimate.py`가 계산 결과를 **별도 파일** `data/roi_estimate.json`에 저장합니다.
- 이 파일에는 `presentation_claim_allowed=false`가 고정되며 실측 ROI와 합쳐지지 않습니다.

> 방향성 검토에는 쓸 수 있지만, 사람 시간이 추정이므로 배수와 절감률은 성과로 확정하지 않습니다.

## 재현/실측 전환

```powershell
# 실측 3회 이상
.\.venv\Scripts\python.exe scripts\manual_roi_timer.py --participant P01
# 실측 CSV로 실제 ROI 계산(추정 파일과 분리)
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m smart_collect.benchmark_roi --use-llm `
  --manual-csv data\manual_time_measurements.csv `
  --output data\roi_benchmark_llm.json
```
