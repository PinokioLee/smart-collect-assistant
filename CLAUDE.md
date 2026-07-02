# CLAUDE.md

This file gives Claude Code the full working context for this repository.

The user is Korean-speaking. Prefer Korean for explanations, UI copy, docs, commit messages when appropriate, and mentor-facing summaries.

## Project Summary

Project name: **Smart Collect Assistant**

This is an AI Master final project / PoC for automating repeated Excel collection work.

The core scenario:

1. A collection request email arrives.
2. The system analyzes the email to extract required fields, deadline, cautions, and validation rules.
3. Users upload multiple Excel submission files.
4. The system validates rows using deterministic rules.
5. It merges only valid rows.
6. It creates an error report for invalid rows.
7. It generates a final summary and optional guide/request email draft.

The central design message:

```text
LLM이 잘하는 자연어 메일 이해와,
규칙 기반 코드가 잘하는 엑셀 검증을 분리했다.

AI에게는 메일을 읽게 하고,
엑셀 검사는 정확한 계산기 같은 코드에게 맡겼다.
LangGraph는 Agent들이 어떤 순서로 일할지 정해주는 반장 역할이다.
```

## Current Status

The project is already functional as a local PoC. Most items in "User's Requested Next Improvements" below are now implemented (see per-item status) — only harder sample Excel generation (#2) remains pending.

Verified 2026-07-03:

- `pytest tests -q` passed: 56 tests.
- `npm run build` in `frontend` passed.
- `python -m backend.smart_collect.benchmark` runs and writes `data/benchmark_metrics.json`.
- GitHub repository is public:
  - `https://github.com/PinokioLee/smart-collect-assistant`
- Latest known pushed branch: `master`.

`docs/기술_설명_멘토용.md` (mentor-facing technical explainer) exists and is kept in sync with implementation status.

## Tech Stack

Backend:

- Python 3.11+
- FastAPI
- Uvicorn
- LangGraph
- LangChain / LangChain OpenAI
- Azure OpenAI / OpenAI API
- pandas
- openpyxl
- Pydantic
- python-dotenv
- python-multipart
- pytest
- httpx
- optional Gmail API adapter
- optional Langfuse
- optional RAG structure

Frontend:

- React
- TypeScript
- Vite
- Axios

Storage:

- Local file storage under `data/`

Source control:

- Git / GitHub

## Key Architecture

```text
React + TypeScript UI
  -> FastAPI API server
    -> LangGraph workflow
      -> Requirement Analysis Agent
      -> Supervisor / Planning Agent
      -> optional RAG Reference Agent
      -> Excel Validation Agent
      -> Self-Correction Agent
      -> Merge
      -> Error Report
      -> Report Agent
```

Important design boundary:

- LLM is used for natural-language email understanding and guide/mail draft generation.
- Excel validation and merging must remain deterministic, using pandas/openpyxl.
- Do not let LLM decide actual row validity.

## Main Files

Backend:

- `backend/api.py`
  - FastAPI API server.
  - Existing endpoints include:
    - `GET /api/health`
    - `GET /api/sample-email`
    - `POST /api/gen-samples`
    - `POST /api/gen-project-samples` — generates the 5-file common-project sample set (item 6)
    - `POST /api/collect`
    - `POST /api/update-fields`
    - `POST /api/sync-common-fields` — reference-file based bulk sync (item 7)
    - `POST /api/save-style-mail`
    - `POST /api/upload-style-mails` — upload past mails for style RAG (item 4)
    - `GET /api/style-mails`
    - `POST /api/guide`
    - `POST /api/send-email`
    - `POST /api/send-request-mail` — editable subject/body/attachment/recipients send form
    - `POST /api/track`
    - `GET /api/download-file/{request_id}/{filename}`
    - `GET /api/download/{request_id}/{kind}`

- `backend/smart_collect/graph.py`
  - LangGraph workflow.

- `backend/smart_collect/pipeline.py`
  - Node implementations and non-graph orchestration.

- `backend/smart_collect/state.py`
  - Pydantic models such as `AgentState`, `ExtractedRequirements`, `ValidationRule`, `ExcelValidationResult`.

- `backend/smart_collect/sample_data.py`
  - `generate_samples()`: fixed sample email + 3 department Excel files with 4 seeded errors (missing required value x2, duplicate row, invalid code value + invalid date format). Still needs improvement for harder samples (see item 2).
  - `generate_project_common_samples()`: 5-file common-project sample set for the reference-based bulk sync flow (item 6, implemented).

- `backend/smart_collect/tools/excel_tools.py`
  - Excel loading, validation, merging, error report generation, common field update logic, and `sync_common_fields_from_reference()` (matches rows by `프로젝트번호` when present, else applies the reference file's first row).

- `backend/smart_collect/tools/requirement_tools.py`
  - Email analysis and validation rule generation.

- `backend/smart_collect/tools/tot_rules.py`
  - Tree of Thoughts style rule candidate selection.

- `backend/smart_collect/tools/self_correction.py`
  - Safe correction for date/code-value errors.

- `backend/smart_collect/tools/guide_tools.py`
  - Guide and mail draft generation.

- `backend/smart_collect/tools/email_tools.py`
  - Mock email adapter and Gmail send adapter.
  - Current Gmail support is mainly send-oriented, not full inbox search.

- `backend/smart_collect/tools/submission_tools.py`
  - Current submission tracking is mock/rule-based, not Gmail inbox based.

- `backend/smart_collect/tools/rag_tools.py`
  - Lightweight local keyword search under `docs/reference` (no FAISS/embeddings). Backs the style RAG for request-mail drafts — searches `docs/reference/style_samples/` (past mails saved via `/api/save-style-mail` or uploaded via `/api/upload-style-mails`) and injects tone/structure examples into the draft prompt.

Frontend:

- `frontend/src/App.tsx`
  - Main UI: 4-stage pipeline console (① 요청 메일 보내기 ② 검증·병합 ③ 제출 현황·리마인드 ④ 공통 항목 수정). No mojibake found as of 2026-07-03; still fix if any turns up while touching UI copy.

- `frontend/src/api.ts`
  - Axios API client.

- `frontend/src/types.ts`
  - Frontend response types.

- `frontend/src/styles.css`
  - Main styling.

Docs / submission:

- `README.md`
- `docs/제출_체크리스트.md`
- `docs/시연영상_대본.md`
- `docs/기술_설명_멘토용.md`
- `AI_talent_lab/E2E 서비스 개발.md`
- `AI_talent_lab/테스트 및 고도화.md`
- `presentation/AI_Master_최종발표_이형진_08079.pptx`

## Existing Behavior To Know

### Sample Mail

The UI button is labeled "내장 샘플 메일 불러오기" (item 1, done) to make clear it loads the fixed mock email from `backend/smart_collect/sample_data.py`.

It does **not** read Gmail.

### Gmail / MCP Scope

The user clarified the desired scope:

- The app does not need to automatically monitor Gmail.
- It is acceptable for Claude Code to use Gmail MCP manually when the user requests it.
- Flow:

```text
User asks / clicks / requests Gmail check
  -> Claude Code uses Gmail MCP to search selected Gmail messages
  -> Claude Code brings selected email subject/body/attachment info into the workflow
  -> User runs validation
```

Important distinction:

```text
Gmail MCP
= Claude Code or another agent reads Gmail as a tool.

App Gmail integration
= FastAPI backend directly uses Gmail API/OAuth to read mailbox.
```

For this project, mentor-facing explanation can say:

```text
1차 PoC에서는 Gmail을 상시 자동 감시하지 않고,
사용자가 필요할 때만 MCP-assisted manual import 방식으로 메일을 가져오는 Human-in-the-loop 흐름으로 설계했다.
실제 Gmail API 기반 자동 수신함 검색과 첨부 수집은 후속 확장 범위다.
```

### Submission Tracking

Current `/api/track` does **not** inspect actual Gmail replies.

It compares sample recipients with submitted identifiers or filenames using deterministic matching.

If mentor asks:

```text
현재는 mock 제출 추적이다.
실제 회신 메일 기반 제출 확인은 Gmail MCP 또는 Gmail API 읽기 권한을 통해 후속 확장 가능하다.
```

### Email Sending

Current default is mock.

`backend/smart_collect/tools/email_tools.py` has:

- `MockEmailAdapter`
- `GmailApiEmailAdapter`

Actual Gmail sending requires OAuth credentials and `EMAIL_SEND_MODE=gmail`.

Do not claim production Gmail sending/inbox automation unless actually verified.

## User's Requested Next Improvements

The user tested the app and requested the following changes. Status as of 2026-07-03: items 1, 3, 4, 6, 7 are implemented; item 5 is a documentation/explanation stance (no code needed); item 2 is the only one still pending.

### 1. Clarify Sample Mail — DONE

Suggested UI wording was applied:

- `내장 샘플 메일 불러오기` (button label, `frontend/src/App.tsx`)
- Gmail is not read by the app; the mentor cheat sheet already explains the Gmail MCP Human-in-the-loop scope.

### 2. Harder Sample Excel Generation — PENDING

Current sample Excel generation is too easy.

Need to generate more realistic/harder sample Excel files with errors such as:

- missing required values
- missing required columns
- invalid date format
- invalid code values
- duplicates across files
- numeric fields with commas/currency text
- schema drift / extra columns / different column order
- maybe hidden-like operational fields or notes

Keep validation deterministic.

Current state (`backend/smart_collect/sample_data.py::generate_samples`): only 4 seeded errors across 3 files (2x missing required value, 1x duplicate row, 1x invalid code value + invalid date format on the same row). None of the harder cases above (missing columns, comma/currency numerics, schema drift, extra/reordered columns) are implemented yet. This is the next real implementation task if the user asks to continue.

### 3. Remove Execution Option Checkboxes — DONE

`frontend/src/App.tsx` no longer has `LangGraph workflow 사용` / `메일 분석에 LLM 사용` checkboxes. `collect()` is always called with `useGraph: true, useLlm: true` (`frontend/src/App.tsx:153`). Backend still accepts `use_graph`/`use_llm` form params for compatibility.

### 4. RAG Based On Uploaded Previous Emails — DONE

Implemented as the "style RAG" for request-mail drafts (not a generic doc-QA RAG):

- `POST /api/save-style-mail` — save pasted text as a style sample.
- `POST /api/upload-style-mails` — upload `.txt`/`.md`/`.eml` files, saved under `docs/reference/style_samples/`.
- `GET /api/style-mails` — list saved style samples.
- `backend/smart_collect/tools/rag_tools.py` searches `style_samples/` by keyword and injects matching past mails into the request-mail draft prompt (tone/structure reference), badged "내 발송 스타일 반영됨" in the UI.
- This is retrieval, not model training — keep using the correct explanation:

```text
기존 메일을 모델에 학습시키는 것이 아니라,
업로드한 과거 메일을 참고 문서처럼 검색해서 프롬프트에 넣는 RAG 방식이다.
```

### 5. Submission Tracking Explanation — STANCE ONLY (no code change)

User asked whether submission tracking checks replies to sent email.

Current answer:

- No. Current implementation is mock/file-identifier based.

Potential future:

- Gmail MCP assisted check:
  - user asks Claude Code to check replies
  - Claude Code searches Gmail thread/replies
  - Claude Code returns submitted/missing list
- Full app integration:
  - Gmail API read scopes
  - store sent `message_id` or subject
  - search replies
  - detect Excel attachments
  - match sender emails to recipient list

For now, do not imply automatic reply checking is implemented.

### 6. Common Project Sample Excel Generation — DONE

`backend/smart_collect/sample_data.py::generate_project_common_samples()` generates 5 Excel files under `data/samples/project_common/`, sharing the 9 common columns (`프로젝트명`, `프로젝트번호`, `수주금액`, `매출액`, `마진`, `원가`, `프로젝트 시작일자`, `종료일자`, `담당자`) plus 3 unique columns each: 프로젝트_기준정보 (계약), 프로젝트_재무관리 (재무), 프로젝트_수행관리 (수행), 프로젝트_인력관리 (인력), 프로젝트_리스크품질 (리스크/품질). Exposed via `POST /api/gen-project-samples` and the `프로젝트 샘플 5개 생성` button.

### 7. Reference File Based Bulk Update — DONE

Implemented as designed:

- `backend/smart_collect/tools/excel_tools.py::sync_common_fields_from_reference(reference_file, target_files, common_columns, output_dir)` — matches rows by `프로젝트번호` when present in both reference and target, otherwise applies the reference file's first row's common values to all target rows.
- `POST /api/sync-common-fields` (multipart: `reference_file` + `target_files[]`) saves updated files under `data/updated_files/{request_id}/` and returns download links.
- UI (`frontend/src/App.tsx`, 4th pipeline stage) has exactly the requested controls: `프로젝트 샘플 5개 생성`, `기준 파일 업로드`, `수정 대상 파일 업로드`, `기준 파일 값으로 공통 항목 동기화`.

## Current Validation Metrics

Benchmark metrics currently show roughly:

- F1: 100%
- reproducibility standard deviation: 0
- 46 rows processed in around 0.05 seconds
- safe self-correction rate: 100%

Use `data/benchmark_metrics.json` for exact values.

Regenerate with:

```powershell
.\.venv\Scripts\python.exe -m backend.smart_collect.benchmark
```

## Run Commands

Backend:

```powershell
cd C:\Users\LHJ\AI_Master
.\.venv\Scripts\python.exe backend\api.py
```

Frontend:

```powershell
cd C:\Users\LHJ\AI_Master\frontend
npm run dev
```

Tests:

```powershell
cd C:\Users\LHJ\AI_Master
.\.venv\Scripts\python.exe -m pytest tests -q
```

Frontend build:

```powershell
cd C:\Users\LHJ\AI_Master\frontend
npm run build
```

CLI demo:

```powershell
cd C:\Users\LHJ\AI_Master
.\.venv\Scripts\python.exe backend\cli.py demo
```

Benchmark:

```powershell
cd C:\Users\LHJ\AI_Master
.\.venv\Scripts\python.exe -m backend.smart_collect.benchmark
```

## Development Rules

Follow these rules when editing:

- Keep original Excel files unchanged.
- Generate result files separately.
- Do not claim Gmail inbox automation unless implemented and verified.
- Do not claim production RAG/FAISS unless implemented and verified.
- Do not call LLM for deterministic Excel row validation.
- Keep validation logic reproducible.
- Preserve Korean business-domain terms in user-facing text.
- If touching UI copy, fix mojibake/corrupted Korean strings.
- Use existing project patterns before adding new abstractions.
- Run tests and frontend build after substantial changes.
- Check `git status` before committing because the worktree may contain user changes.

## Mentor Explanation Cheat Sheet

### Why not use LLM for all Excel validation?

```text
엑셀 검증은 창의적인 답이 아니라 정확하고 재현 가능한 답이 필요합니다.
LLM은 메일 이해에는 강하지만, 행 번호와 오류 유형을 항상 동일하게 보장하기 어렵습니다.
그래서 메일 분석은 LLM, 엑셀 검증은 pandas/openpyxl 기반 규칙으로 분리했습니다.
```

### Why LangGraph?

```text
Requirement Analysis, Planning, Validation, Self-Correction, Report처럼 역할이 나뉜 Agent 흐름을 명확히 보여주기 위해 LangGraph를 사용했습니다.
단순 함수 호출보다 멀티 에이전트 구조와 실행 순서를 설명하기 좋습니다.
```

### What is MCP Gmail scope?

```text
MCP는 앱이 직접 Gmail을 읽는 기능이 아니라 Claude Code 같은 에이전트가 Gmail을 확인하는 도구입니다.
1차 PoC에서는 상시 자동 감시가 아니라 사용자가 필요할 때만 MCP로 메일을 확인해 가져오는 Human-in-the-loop 방식으로 설계했습니다.
```

### What is RAG with previous mails?

```text
기존 메일을 모델에 다시 학습시키는 것이 아닙니다.
업로드한 과거 메일을 참고 문서처럼 검색해서, 가이드와 메일 초안 생성 프롬프트에 넣는 방식입니다.
```

### What is Self-Correction?

```text
Self-Correction은 모든 오류를 자동 수정하는 기능이 아닙니다.
날짜 형식과 코드값처럼 의미가 명확한 오류만 안전하게 정규화하고,
필수값 누락과 중복은 사용자 확인이나 재제출 대상으로 남깁니다.
```

## Suggested Next Implementation Plan

Items 1, 3, 4, 6, 7 from "User's Requested Next Improvements" are done. If the user asks Claude Code to continue implementation, the remaining work is:

1. Improve hard sample Excel generation (item 2) — extend `generate_samples()` with missing required columns, comma/currency-formatted numeric fields, schema drift (extra/reordered/renamed columns), and duplicate-across-files cases, while keeping validation deterministic.
2. Run after any change:
   - `pytest tests -q`
   - `npm run build`
   - `python backend/cli.py demo`

## Git Notes

Before finalizing:

```powershell
git status --short --branch
git diff
```

If committing:

```powershell
git add CLAUDE.md docs/기술_설명_멘토용.md
git commit -m "docs: add Claude Code project context"
git push origin master
```

Do not stage generated outputs unless intentionally updating evidence files such as `data/benchmark_metrics.json`.

