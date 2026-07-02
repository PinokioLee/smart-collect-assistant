# Gmail MCP 스타일 기반 요청 메일 초안 — 설계 문서

작성일: 2026-07-03
대상 프로젝트: Smart Collect Assistant (AI Master 최종 과제 PoC)
범위: 기존 개선사항 #1, #3, #4, #5 통합. (#2, #6, #7은 별도 스펙)

## 1. 배경과 목표

### 실제 업무 흐름
```
1. 팀장 → 사용자에게 "이 내용 취합해 주세요" 메일 포워딩
   (포워딩 메일에는 원본 요청 스레드가 아래에 쭉 붙어있음)
2. 사용자는 포워딩 스레드를 아래부터 읽고 무엇을 취합해야 하는지 파악
3. 어떻게 작성해달라고 할지 정리
4. 작성해야 할 사람들(제출자)에게 '수집 요청 메일' 발송  ← 최종 결과물
5. 제출자들이 그 메일을 읽고 엑셀을 작성해 사용자에게 전달
   (여기서부터 기존 Smart Collect 검증/병합 파이프라인)
```

### 목표
- 4번 단계("제출자에게 보낼 수집 요청 메일 초안")를 자동 생성한다.
- 초안은 **사용자가 그동안 발송해온 요청 메일의 톤·구성(스타일)** 을 모방한다.
- Gmail 연동은 **MCP-assisted** 방식으로 한다: Claude Code(에이전트)가 Gmail을 읽어 재료를 앱에 전달하고, 앱이 초안을 생성한다.

### 핵심 설계 경계 (기존 프로젝트 철학 유지)
```
Gmail MCP = Claude Code가 Gmail을 읽는 도구 (앱이 직접 읽지 않음)
앱(FastAPI) = 재료를 받아 요구분석 + 스타일 RAG + 초안 생성
엑셀 검증/병합 = 여전히 결정론적 코드(pandas/openpyxl), LLM 아님
```

비목표(Non-goals):
- 앱 백엔드가 직접 Gmail 수신함을 상시 자동 감시하지 않는다.
- 과거 메일을 모델에 "학습"시키지 않는다. 참고 문서로 검색(RAG)해 프롬프트에 주입할 뿐이다.

## 2. 아키텍처와 데이터 흐름

```
[Claude Code / Gmail MCP]                    [App: FastAPI + React]
  ① 팀장 포워딩 메일 검색·읽기
     (search_threads → get_thread)
  ② Sent 검색: 과거 취합요청 메일 N개
        │
        ├── POST /api/save-style-mail ───────►  docs/reference/style_samples/*.txt
        │                                         (스타일 코퍼스)
        └── 포워딩 본문(subject/body) ─────────►  POST /api/guide
                                                    ├─ analyze_collection_email(subject, body)
                                                    │    → 취합 항목/기한/주의사항 (포워딩 스레드 파악)
                                                    ├─ retrieve_style_samples(query)
                                                    │    → 내 과거 발송 메일 top-k
                                                    ├─ generate_writing_guide(req, references)
                                                    └─ create_request_mail(guide, ..., style_samples)
                                                         → 내 스타일 요청 초안 (subject/body)
                                                    ◄──── UI 표시 (섹션 4)
  ③ 사용자 승인
  ④ create_draft (MCP)
     → Gmail 임시보관함에 초안 저장
     → 사용자가 실제 Gmail에서 확인·발송
```

### 왜 이 구조인가
- 기존 `/api/guide`가 이미 `분석 → 가이드 → 요청 메일 초안` 흐름을 갖고 있어 재활용한다.
- `generate_writing_guide(req, references=...)`는 이미 `references` 인자를 받으므로 스타일 주입 지점이 존재한다.
- `rag_tools`가 이미 `docs/reference` 키워드 검색을 하므로, 스타일 샘플을 하위 폴더에 저장하면 그대로 검색된다.

## 3. 컴포넌트별 상세 설계

### 3.1 `rag_tools.py` — 스타일 샘플 검색 추가
새 함수:
```python
STYLE_DIR = REFERENCE_DIR / "style_samples"

def retrieve_style_samples(query: str, top_k: int = 3) -> list[dict]:
    """사용자의 과거 발송 요청 메일을 검색해 스타일 예시로 반환.
    Returns: [{title, snippet}]  (snippet은 본문 전체 또는 앞부분)
    """
```
- 단위 책임: "스타일 코퍼스에서 관련 과거 메일을 찾는다." 입력=질의 문자열, 출력=예시 목록, 의존=`STYLE_DIR` 파일들.
- `STYLE_DIR`가 비어 있으면 빈 리스트 반환 → 상위에서 스타일 없이 폴백.

### 3.2 `guide_tools.py` — 스타일 주입
- `create_request_mail(guide_body, recipients, deadline, attachment_name, style_samples=None)`:
  - `style_samples`가 있으면 프롬프트에 "아래는 내가 평소 보내는 요청 메일 예시입니다. 이 **톤·인사말·맺음말·구성**을 따라 작성하세요(내용은 위 안내 기준)." 형태로 최대 2~3개 주입.
  - 없으면 기존 동작 유지(폴백 보장).
- `generate_writing_guide`는 이미 `references`를 받으므로 스타일 샘플을 references로도 넘겨 가이드 톤에 반영(선택).
- 산출물은 여전히 "초안"까지만. 실제 발송/드래프트 저장은 이 함수 밖.

### 3.3 `api.py` — 엔드포인트
- `POST /api/save-style-mail`
  - 주 경로: JSON payload `{filename?, subject?, body}` — Claude Code가 MCP로 가져온 Sent 메일을 이 형태로 저장.
  - 폴백 경로: 사용자가 UI에서 `.txt/.md` 파일 직접 업로드(#4의 기존 요구 흡수).
  - `docs/reference/style_samples/`에 `.txt`로 저장. 파일명 없으면 타임스탬프 사용.
  - 반환: `{saved: path, count: 현재 스타일 샘플 총 개수}`
- `GET /api/style-mails` (선택): 현재 저장된 스타일 샘플 개수/목록 → UI 배지용.
- `POST /api/guide` 확장:
  - 기존 시그니처(`subject`, `body`) 유지.
  - 내부에서 `retrieve_style_samples(req.request_title + fields)` 호출 → `generate_writing_guide`와 `create_request_mail`에 전달.
  - 반환 dict에 `style_used: bool`, `style_sources: [파일명]` 추가.

### 3.4 프론트엔드 `App.tsx` / `api.ts` / `types.ts`
- 섹션 1 "취합 요청 메일":
  - `샘플 메일 불러오기` 버튼 라벨 → `내장 샘플 메일` (내장임을 명시). (#1)
  - 안내문 추가: "Gmail 메일은 Claude Code가 MCP로 가져와 아래에 붙여넣습니다." + subject/body는 기존 입력 필드 그대로 사용(붙여넣기 대상).
- 섹션 3 "실행 옵션":
  - `useGraph`, `useLlm` **체크박스 2개 제거**. (#3)
  - `collect()` 호출은 항상 `useGraph=true, useLlm=true` (기본값 유지, UI 노출만 제거).
  - 상태 변수 `useGraph/useLlm`도 제거하거나 상수화.
- 섹션 4 가이드 패널:
  - `style_used`면 "내 과거 발송 스타일 반영됨" 배지 + `style_sources` 표시.
  - 스타일 샘플이 0개면 "스타일 샘플 없음(기본 톤)" 안내.
- 제출 추적 패널(#5):
  - 문구에 "현재는 파일 식별자 기반 mock 추적입니다. 실제 회신 확인은 Claude Code의 Gmail MCP로 수행할 수 있습니다." 명시.

### 3.5 문서 (`docs/시연영상_대본.md`, `docs/기술_설명_멘토용.md`)
- Gmail MCP-assisted 흐름(①~④)을 시연 대본에 반영.
- 멘토 설명에 "MCP vs 앱 Gmail 통합" 구분과 "스타일 RAG ≠ 학습" 문구 반영.

## 4. MCP-assisted 운영 절차 (Claude Code가 대화에서 수행)
1. 사용자가 "Gmail에서 팀장 취합 메일 가져와줘" 요청.
2. Claude Code: `search_threads`로 대상 스레드 검색 → `get_thread`로 포워딩 본문 확보.
3. Claude Code: `search_threads`(Sent/from:me)로 과거 취합요청 메일 N개 확보 → 각각 `/api/save-style-mail` 저장.
4. Claude Code: 포워딩 subject/body를 앱 입력에 넣고(또는 사용자에게 제시) `/api/guide` 실행.
5. 초안 확인·수정 후, `create_draft`로 Gmail 임시보관함에 저장. 사용자가 실제 발송.

주의: MCP 도구는 Claude Code의 도구다. 앱은 이 단계에서 Gmail을 직접 호출하지 않는다.

## 5. 에러 처리 / 폴백
- 스타일 샘플이 없거나 검색 0건 → 기존 기본 톤으로 초안 생성(기능 저하 없음).
- LLM 실패 → 기존 결정론적 템플릿 폴백(현행 유지).
- Gmail MCP 미가용/미승인 → 사용자가 포워딩 메일을 수동 붙여넣기(폴백 경로 항상 존재).
- `/api/save-style-mail` 잘못된 payload → 400.

## 6. 테스트 계획
- 단위: `retrieve_style_samples` (샘플 유무/검색 순위), `create_request_mail`(style_samples 유무 분기, LLM 없을 때 폴백).
- 통합: `/api/save-style-mail` → `/api/guide`가 `style_used=true` 반환하는지.
- 회귀: 스타일 샘플 없이 `/api/guide`가 기존과 동일 동작(폴백).
- 프론트 빌드: `npm run build` 통과.
- 기존 35개 pytest 유지 + 신규 테스트 추가.

## 7. 명시적 범위 밖 (별도 스펙)
- #2 어려운 샘플 엑셀 생성
- #6 공통항목 프로젝트 샘플 엑셀 5개
- #7 기준 파일 기반 공통항목 일괄 동기화
- 앱 백엔드의 직접 Gmail API 수신함 검색(OAuth read scope) — 후속 확장

## 8. 완료 기준 (Definition of Done)
- 체크박스 2개가 UI에서 사라지고 collect는 항상 graph+llm으로 호출된다.
- 샘플 메일 버튼이 "내장 샘플"임을 명확히 한다.
- `/api/save-style-mail`로 저장한 과거 메일이 `/api/guide` 초안 톤에 반영되고, `style_used`가 UI에 표시된다.
- 제출 추적 UI 문구가 mock/MCP-assisted임을 명확히 한다.
- `pytest tests -q`, `npm run build`, `python backend/cli.py demo` 통과.
- 과장 금지 규칙 준수: 앱 자동 수신함 감시/모델 학습을 주장하지 않는다.
