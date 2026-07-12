# Smart Collect Assistant

취합 요청·작성 가이드·파일 병합 자동화 시스템 (1차 PoC)

여러 부서/담당자에게 받은 **엑셀 파일을 자동으로 검증·병합**하고, 취합 요청
**메일을 분석**해 검증 기준을 만들어 주는 멀티 에이전트 업무 자동화 시스템.

```
취합 요청 메일 1건  →  작성 항목/제출 기준 추출  →  제출 엑셀 N개 업로드
   →  필수값/날짜형식/중복/코드값 검증  →  정상 데이터만 병합  →  오류 보고서  →  요약
```

---

## 아키텍처

```
┌──────────────┐   HTTP/multipart   ┌───────────────────────────────────────┐
│ React + TS   │ ─────────────────► │ FastAPI (backend/api.py)              │
│ (frontend)   │ ◄───────────────── │                                       │
└──────────────┘   JSON + 파일      │  LangGraph Multi-Agent (graph.py)     │
                                    │   START → Requirement Analysis        │
                                    │        → Supervisor(Planning)         │
                                    │        → [RAG?] → Excel Validation     │
                                    │        → Merge → Error Report → Report │
                                    └───────────────────────────────────────┘
                                              │
                       pandas/openpyxl 규칙기반 검증·병합 (LLM 아님)
                       Azure OpenAI = 메일 분석에만 사용 (없으면 휴리스틱)
```

### 전문 Agent / 노드

| Agent | 노드 | 역할 | 방식 |
|---|---|---|---|
| Supervisor | StartNode / PlanningNode | 흐름 제어, 검증 규칙 생성, RAG 분기 | 상태 기반 |
| Requirement Analysis | RequirementAnalysisNode | 메일 → 작성항목/마감/주의사항 | Azure LLM ↔ 휴리스틱 폴백 |
| RAG Reference (선택) | RagReferenceNode | 기준 문서 검색 | 키워드 (운영시 FAISS) |
| Excel Validation | ExcelValidationNode / ExcelMergeNode / ErrorReportNode | 4종 검증·병합·보고서 | **pandas/openpyxl 규칙기반** |
| Report | ReportNode | 최종 요약 | 템플릿 |

### 검증 규칙 (4종)

| 유형 | 내용 |
|---|---|
| 필수값 누락 | 필수 컬럼 부재 / 빈 값 |
| 날짜 형식 오류 | 날짜 컬럼이 `YYYY-MM-DD` 아님 |
| 허용되지 않은 코드값 | 긴급도 ∉ {상, 중, 하} |
| 중복 데이터 | (부서명, 요청시스템, 개선요청내용) 중복 |

> 검증/병합은 **결정론적 규칙**으로 처리해 동일 입력 → 동일 결과를 보장한다.
> 원본 파일은 보존하고 결과는 별도 파일로 생성한다. 오류는 자동 수정하지 않는다.

---

## 빠른 시작

### 1) 백엔드 (Python 3.11+)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r backend/requirements.txt

# (선택) Azure 키 설정
copy .env.example .env            # 값 채우기

# CLI 로 바로 데모 (UI 없이)
python backend/cli.py gen-samples           # 샘플 메일+엑셀 생성
python backend/cli.py run --graph --json     # LangGraph 워크플로우 실행

# API 서버
python backend/api.py             # http://127.0.0.1:8000
```

### 2) 프론트엔드 (Node 20+)

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173  (/api → 8000 프록시)
```

브라우저에서 **샘플 메일 불러오기 → 샘플 엑셀 생성 → 파일 업로드 → 실행**.

---

## CLI 사용법

```bash
# 샘플로 실행 (휴리스틱)
python backend/cli.py run --no-llm

# LangGraph 워크플로우 + JSON 출력
python backend/cli.py run --graph --json

# 현실 난이도 하드 샘플로 실행 (오류 5종·스키마 드리프트·통화 숫자·파일 간 중복)
python backend/cli.py gen-samples --hard      # data/samples/hard/ 생성
python backend/cli.py run --hard --graph

# 내 파일로
python backend/cli.py run --subject "..." --body-file mail.txt \
    --excel a.xlsx b.xlsx c.xlsx
```

---

## 테스트

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

검증 로직(필수/날짜/중복/코드값/병합/보고서)을 샘플 데이터로 회귀 검증한다.

---

## 디렉터리

```
backend/
  cli.py                  CLI 진입점
  api.py                  FastAPI 서버
  requirements.txt
  smart_collect/
    config.py             환경설정/경로/토글
    state.py              AgentState (pydantic)
    llm.py                Azure OpenAI 어댑터 (없으면 None→휴리스틱)
    pipeline.py           노드 함수 + 선형 오케스트레이터
    graph.py              LangGraph 멀티에이전트 그래프
    observability.py      로깅 + 선택적 Langfuse
    sample_data.py        데모 샘플 생성기
    tools/
      excel_tools.py      검증/병합/보고서 (규칙기반)
      requirement_tools.py 메일 분석 + 검증규칙 생성
      report_tools.py     결과 요약
      rag_tools.py        선택적 RAG
frontend/                 React + TS + Vite
tests/                    pytest
data/                     samples / merged_files / error_reports / uploads
```

---

## 범위 (1차 PoC)

**포함**: 메일 분석 · 엑셀 4종 검증 · 정상 병합 · 오류 보고서 · 결과 요약 · LangGraph 흐름 · API · UI
**제외(후속)**: 실제 Gmail/사내메일 연동, 메일 발송, 제출자 추적/리마인드, 정식 RAG(FAISS) 운영, Langfuse 정식 연동
