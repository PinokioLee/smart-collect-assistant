# Gmail MCP 스타일 기반 요청 메일 초안 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팀장이 포워딩한 취합 메일을 분석하고, 사용자의 과거 발송 메일 스타일을 RAG로 반영한 제출자용 요청 메일 초안을 앱에서 생성한다. (MCP-assisted)

**Architecture:** 기존 `/api/guide` 파이프라인(분석→가이드→요청초안)을 재활용한다. 스타일 코퍼스는 `docs/reference/style_samples/`에 저장하고 `rag_tools.STYLE_DIR` 단일 경로로 저장·검색을 통일한다. Gmail 읽기/드래프트는 앱이 아니라 Claude Code(MCP)가 대화에서 수행하고, 결과 텍스트만 앱에 전달한다.

**Tech Stack:** Python 3.11, FastAPI, pytest + `fastapi.testclient`, React + TypeScript + Vite, Axios.

## Global Constraints

- UI/문서 문자열은 한국어 유지. UI 손대면 깨진 한글(mojibake) 수정.
- 과장 금지: 앱이 Gmail 수신함을 자동 감시한다고 하지 않는다. 과거 메일을 "학습"한다고 하지 않는다(RAG 검색·프롬프트 주입일 뿐).
- 엑셀 검증/병합은 결정론적 코드 유지. LLM으로 행 유효성 판단 금지.
- 원본 엑셀 파일 변경 금지. 결과물은 별도 저장.
- 프론트는 항상 `useGraph=true, useLlm=true`로 collect 호출(UI 노출만 제거).
- 스타일 저장 단일 경로: `rag_tools.STYLE_DIR` (= `ROOT_DIR/docs/reference/style_samples`). api.py는 `from smart_collect.tools import rag_tools` 후 `rag_tools.STYLE_DIR` 참조.
- LLM 미가용 시 결정론적 폴백 유지(테스트 환경엔 Azure 키 없음 전제).
- 커밋은 기능 단위로 자주. 각 태스크 끝에 커밋.

## File Structure

- `backend/smart_collect/tools/rag_tools.py` — (수정) `STYLE_DIR` 상수 + `retrieve_style_samples()` 추가.
- `backend/smart_collect/tools/guide_tools.py` — (수정) `_build_style_hint()` + `create_request_mail(..., style_samples=None)`.
- `backend/api.py` — (수정) `/api/save-style-mail`, `/api/style-mails` 추가, `/api/guide` 스타일 RAG 연결.
- `tests/test_style_request.py` — (신규) 위 백엔드 동작 단위·통합 테스트.
- `frontend/src/types.ts` — (수정) `GuideResponse` 스타일 필드.
- `frontend/src/api.ts` — (수정) `saveStyleMail`, `getStyleMails`, `GuideResponse` 확장, `createGuide` 유지.
- `frontend/src/App.tsx` — (수정) 체크박스 제거, 샘플메일 라벨/안내, 스타일 관리 UI·배지, 제출추적 문구.
- `docs/시연영상_대본.md`, `docs/기술_설명_멘토용.md` — (수정) MCP 흐름·스타일 RAG 반영.

---

### Task 1: 스타일 샘플 검색 (`retrieve_style_samples`)

**Files:**
- Modify: `backend/smart_collect/tools/rag_tools.py`
- Test: `tests/test_style_request.py`

**Interfaces:**
- Produces: `rag_tools.STYLE_DIR: Path`, `rag_tools.retrieve_style_samples(query: str, top_k: int = 3) -> list[dict]` — 각 dict는 `{"title": str, "snippet": str}`. 폴더 없거나 파일 없으면 `[]`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_style_request.py` 생성:
```python
"""Gmail MCP 스타일 기반 요청 초안 기능 테스트."""

from fastapi.testclient import TestClient

from api import app
from smart_collect.tools import rag_tools


# ---------- Task 1: retrieve_style_samples ----------

def test_style_samples_empty_when_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path / "none")
    assert rag_tools.retrieve_style_samples("취합 요청") == []


def test_style_samples_returns_saved(monkeypatch, tmp_path):
    d = tmp_path / "style"
    d.mkdir()
    (d / "mail1.txt").write_text(
        "안녕하세요. 취합 협조 요청드립니다.", encoding="utf-8"
    )
    monkeypatch.setattr(rag_tools, "STYLE_DIR", d)
    out = rag_tools.retrieve_style_samples("취합 요청")
    assert len(out) == 1
    assert out[0]["title"] == "mail1.txt"
    assert "협조" in out[0]["snippet"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'STYLE_DIR'` 또는 `retrieve_style_samples`).

- [ ] **Step 3: 최소 구현**

`backend/smart_collect/tools/rag_tools.py`의 `REFERENCE_DIR` 정의 아래에 추가:
```python
STYLE_DIR = REFERENCE_DIR / "style_samples"


def retrieve_style_samples(query: str, top_k: int = 3) -> list[dict]:
    """사용자의 과거 발송 요청 메일을 검색해 스타일 예시로 반환한다.

    스타일 반영이 목적이므로 질의 매칭이 0이어도 파일이 있으면 포함하고,
    매칭 점수 → 최근 수정순으로 정렬한다.
    Returns: [{"title": 파일명, "snippet": 본문 앞부분}]
    """
    if not STYLE_DIR.exists():
        return []
    terms = [t for t in query.replace("/", " ").split() if t]
    scored: list[tuple[float, float, str, str]] = []
    for path in STYLE_DIR.rglob("*"):
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = sum(text.count(t) for t in terms) if terms else 0
        score = min(hits / (len(terms) or 1) / 5, 1.0)
        scored.append((score, path.stat().st_mtime, path.name, text[:1500]))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [
        {"title": name, "snippet": snip} for _, _, name, snip in scored[:top_k]
    ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: 커밋**

```bash
git add backend/smart_collect/tools/rag_tools.py tests/test_style_request.py
git commit -m "feat: 스타일 샘플 검색(retrieve_style_samples) 추가"
```

---

### Task 2: 요청 메일 초안 스타일 주입 (`create_request_mail`)

**Files:**
- Modify: `backend/smart_collect/tools/guide_tools.py`
- Test: `tests/test_style_request.py`

**Interfaces:**
- Consumes: 스타일 샘플 `list[dict]` (`{"title","snippet"}`) — Task 1 출력 형태.
- Produces: `guide_tools._build_style_hint(style_samples: list[dict] | None) -> str`; `create_request_mail(guide_body, recipients, deadline, attachment_name, style_samples=None) -> {"mail_subject","mail_body"}`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_style_request.py`에 추가:
```python
# ---------- Task 2: 스타일 힌트 / 요청 메일 ----------

def test_build_style_hint_empty():
    from smart_collect.tools.guide_tools import _build_style_hint
    assert _build_style_hint(None) == ""
    assert _build_style_hint([]) == ""


def test_build_style_hint_includes_examples():
    from smart_collect.tools.guide_tools import _build_style_hint
    hint = _build_style_hint([{"snippet": "안녕하세요 협조바랍니다"}])
    assert "예시 1" in hint
    assert "협조바랍니다" in hint


def test_create_request_mail_accepts_style_samples():
    from smart_collect.tools.guide_tools import create_request_mail
    out = create_request_mail(
        "본문 안내", [{"name": "A"}], "2026-06-12", "form.xlsx",
        style_samples=[{"title": "m", "snippet": "안녕하세요"}],
    )
    assert "mail_subject" in out
    assert "mail_body" in out
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: FAIL (`ImportError: cannot import name '_build_style_hint'`).

- [ ] **Step 3: 최소 구현**

`backend/smart_collect/tools/guide_tools.py`의 `# ---------- 요청 메일 초안 ----------` 섹션에 헬퍼를 추가하고 `create_request_mail` 시그니처/프롬프트를 교체.

헬퍼 추가(요청 메일 섹션 상단):
```python
def _build_style_hint(style_samples: list[dict] | None) -> str:
    """과거 발송 메일을 톤/구성 예시로 주입할 프롬프트 조각을 만든다."""
    if not style_samples:
        return ""
    examples = "\n\n".join(
        f"[예시 {i + 1}] {s.get('snippet', '')[:600]}"
        for i, s in enumerate(style_samples[:3])
    )
    return (
        "\n\n아래는 내가 평소 보내는 요청 메일 예시입니다. "
        "이 인사말·톤·구성·맺음말 스타일을 따라 작성하세요(내용 기준은 위 안내).\n"
        f"{examples}"
    )
```

`create_request_mail` 교체:
```python
def create_request_mail(
    guide_body: str,
    recipients: list[dict],
    deadline: str | None,
    attachment_name: str,
    style_samples: list[dict] | None = None,
) -> dict:
    """작성자에게 보낼 취합 요청 메일 초안(제목/본문)을 생성한다.

    style_samples 가 있으면 사용자의 과거 발송 톤을 모방하도록 프롬프트에 주입한다.
    """
    prompt = (
        "회사 내부 취합 요청 메일 초안을 작성하세요. 정중하고 간결한 업무 톤. "
        "JSON 으로만 응답: {mail_subject, mail_body}\n\n"
        f"안내 내용:\n{guide_body}\n\n제출 기한: {deadline}\n첨부: {attachment_name}\n"
        f"수신자 수: {len(recipients)}명"
        f"{_build_style_hint(style_samples)}"
    )
    content = chat([{"role": "user", "content": prompt}], temperature=0.3)
    data = _try_json(content)
    if data and data.get("mail_body"):
        return {"mail_subject": data.get("mail_subject", "취합 요청"), "mail_body": data["mail_body"]}
    return {
        "mail_subject": "[취합 요청] 자료 작성 협조 요청",
        "mail_body": (
            f"안녕하세요.\n\n{guide_body}\n\n"
            f"제출 기한: {deadline or '안내 참조'}\n첨부 양식: {attachment_name}\n\n"
            "작성 후 본 메일에 회신 부탁드립니다. 감사합니다."
        ),
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: 커밋**

```bash
git add backend/smart_collect/tools/guide_tools.py tests/test_style_request.py
git commit -m "feat: 요청 메일 초안에 과거 발송 스타일 주입"
```

---

### Task 3: 스타일 메일 저장/조회 엔드포인트

**Files:**
- Modify: `backend/api.py`
- Test: `tests/test_style_request.py`

**Interfaces:**
- Consumes: `rag_tools.STYLE_DIR` (Task 1).
- Produces: `POST /api/save-style-mail` (JSON `{filename?, subject?, body}`) → `{"saved": str, "count": int}`; `GET /api/style-mails` → `{"count": int, "files": [str]}`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_style_request.py`에 추가:
```python
# ---------- Task 3: 저장/조회 엔드포인트 ----------

def test_save_style_mail_and_count(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/save-style-mail",
        json={"subject": "취합요청", "body": "안녕하세요 협조바랍니다"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["saved"].endswith((".txt", ".md"))


def test_save_style_mail_requires_body(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    client = TestClient(app)
    r = client.post("/api/save-style-mail", json={"body": "   "})
    assert r.status_code == 400


def test_style_mails_lists_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/style-mails")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert "a.txt" in r.json()["files"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: FAIL (404 on `/api/save-style-mail`).

- [ ] **Step 3: 최소 구현**

`backend/api.py` 상단 import 블록에 `rag_tools` 추가(다른 `smart_collect` import 옆):
```python
from smart_collect.tools import rag_tools  # noqa: E402
```

`/api/update-fields` 정의 아래(또는 `/api/guide` 위)에 두 엔드포인트 추가:
```python
@app.post("/api/save-style-mail")
def save_style_mail(payload: dict) -> dict:
    """과거 발송 요청 메일을 스타일 코퍼스로 저장한다(#4).

    payload: {filename?, subject?, body}
    Claude Code(MCP)가 Sent 메일을 이 형태로 전달하거나, UI 파일 업로드로도 사용.
    """
    body = str(payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="메일 본문(body)이 필요합니다.")
    subject = str(payload.get("subject") or "").strip()
    rag_tools.STYLE_DIR.mkdir(parents=True, exist_ok=True)
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        filename = "style-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if not filename.lower().endswith((".txt", ".md")):
        filename += ".txt"
    dest = rag_tools.STYLE_DIR / Path(filename).name
    content = (f"제목: {subject}\n\n" if subject else "") + body
    dest.write_text(content, encoding="utf-8")
    count = len(
        [p for p in rag_tools.STYLE_DIR.glob("*") if p.suffix.lower() in {".txt", ".md"}]
    )
    return {"saved": str(dest), "count": count}


@app.get("/api/style-mails")
def style_mails() -> dict:
    """저장된 스타일 샘플 개수/목록(#4). UI 배지용."""
    if not rag_tools.STYLE_DIR.exists():
        return {"count": 0, "files": []}
    files = sorted(
        p.name for p in rag_tools.STYLE_DIR.glob("*")
        if p.suffix.lower() in {".txt", ".md"}
    )
    return {"count": len(files), "files": files}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: 커밋**

```bash
git add backend/api.py tests/test_style_request.py
git commit -m "feat: 스타일 메일 저장/조회 엔드포인트 추가"
```

---

### Task 4: `/api/guide` 스타일 RAG 연결

**Files:**
- Modify: `backend/api.py:168-183` (`/api/guide`)
- Test: `tests/test_style_request.py`

**Interfaces:**
- Consumes: `rag_tools.retrieve_style_samples` (Task 1), `create_request_mail(..., style_samples=...)` (Task 2).
- Produces: `/api/guide` 반환 dict에 `style_used: bool`, `style_sources: list[str]` 추가.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_style_request.py`에 추가:
```python
# ---------- Task 4: /api/guide 스타일 연결 ----------

def test_guide_reports_style_used(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    (tmp_path / "past.txt").write_text(
        "안녕하세요. 늘 감사합니다. 협조 부탁드립니다.", encoding="utf-8"
    )
    client = TestClient(app)
    r = client.post(
        "/api/guide",
        data={"subject": "6월 취합", "body": "작성 항목은 부서명, 담당자 입니다."},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["style_used"] is True
    assert "past.txt" in d["style_sources"]


def test_guide_without_style(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path / "empty")
    client = TestClient(app)
    r = client.post(
        "/api/guide",
        data={"subject": "6월 취합", "body": "작성 항목은 부서명 입니다."},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["style_used"] is False
    assert d["style_sources"] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_style_request.py -q`
Expected: FAIL (`KeyError: 'style_used'`).

- [ ] **Step 3: 최소 구현**

`backend/api.py`의 `guide` 함수를 교체:
```python
@app.post("/api/guide")
def guide(subject: str = Form(...), body: str = Form(...)) -> dict:
    """작성 가이드 + 요청 메일 초안 (과거 발송 스타일 RAG 반영)."""
    from smart_collect.tools.guide_tools import create_request_mail, generate_writing_guide
    from smart_collect.tools.requirement_tools import analyze_collection_email
    from smart_collect.tools.submission_tools import SAMPLE_RECIPIENTS

    req = analyze_collection_email(subject, body, prefer_llm=True)
    query = " ".join(filter(None, [req.request_title or "", *req.required_fields]))
    style_samples = rag_tools.retrieve_style_samples(query)
    g = generate_writing_guide(req, references=style_samples or None)
    m = create_request_mail(
        g["guide_body"], SAMPLE_RECIPIENTS, req.deadline, "취합양식.xlsx",
        style_samples=style_samples or None,
    )
    return {
        "extracted": req.model_dump(),
        "guide": g,
        "mail_draft": m,
        "llm_used": settings.azure_ready,
        "style_used": bool(style_samples),
        "style_sources": [s["title"] for s in style_samples],
    }
```

- [ ] **Step 4: 테스트 통과 + 전체 회귀 확인**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS (기존 35개 + 신규 10개 = 45 passed).

- [ ] **Step 5: 커밋**

```bash
git add backend/api.py tests/test_style_request.py
git commit -m "feat: /api/guide에 과거 발송 스타일 RAG 연결"
```

---

### Task 5: 프론트 API/타입 확장

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`

**Interfaces:**
- Consumes: `/api/save-style-mail`, `/api/style-mails`, `/api/guide`의 신규 필드(Task 3–4).
- Produces: `saveStyleMail(subject, body)`, `getStyleMails()`, `GuideResponse.style_used/style_sources`.

- [ ] **Step 1: `GuideResponse`에 스타일 필드 추가**

`frontend/src/api.ts`의 `GuideResponse` 인터페이스 끝(`llm_used: boolean;` 아래)에 추가:
```typescript
  style_used: boolean;
  style_sources: string[];
```

- [ ] **Step 2: 스타일 API 함수 추가**

`frontend/src/api.ts`의 `createGuide` 함수 아래에 추가:
```typescript
export interface StyleMailsResponse {
  count: number;
  files: string[];
}

export async function getStyleMails(): Promise<StyleMailsResponse> {
  const { data } = await client.get<StyleMailsResponse>("/style-mails");
  return data;
}

export async function saveStyleMail(subject: string, body: string): Promise<{ saved: string; count: number }> {
  const { data } = await client.post("/save-style-mail", { subject, body });
  return data;
}
```

- [ ] **Step 3: 빌드로 타입 검증**

Run: `cd C:\Users\LHJ\AI_Master\frontend; npm run build`
Expected: 빌드 성공(타입 에러 없음).

- [ ] **Step 4: 커밋**

```bash
git add frontend/src/api.ts frontend/src/types.ts
git commit -m "feat: 프론트 스타일 메일 API/타입 추가"
```

---

### Task 6: 실행 옵션 체크박스 제거 (#3)

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces: collect는 항상 `useGraph=true, useLlm=true`. UI에서 "3. 실행 옵션" 섹션 제거.

- [ ] **Step 1: 상태·핸들러 정리**

`frontend/src/App.tsx`에서 `const [useGraph, setUseGraph] = useState(true);`와 `const [useLlm, setUseLlm] = useState(true);` 두 줄을 삭제하고, `run()` 내부 `collect({ subject, body, useGraph, useLlm, files })` 호출을 다음으로 교체:
```typescript
      const res = await collect({ subject, body, useGraph: true, useLlm: true, files });
```

- [ ] **Step 2: 체크박스 UI 제거**

`App.tsx`에서 아래 블록 전체(섹션 3)를 삭제:
```tsx
          <h2>3. 실행 옵션</h2>
          <label className="check">
            <input type="checkbox" checked={useGraph} onChange={(e) => setUseGraph(e.target.checked)} />
            LangGraph 멀티에이전트 워크플로우 사용
          </label>
          <label className="check">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            메일 분석에 LLM 사용 (키 없으면 자동 휴리스틱)
          </label>
```
그리고 이어지는 `<h2>2. 제출 엑셀 업로드</h2>` 다음의 `검증 · 병합 실행` 버튼은 그대로 둔다(섹션 번호는 변경 안 해도 무방하나, 남은 "3. 실행 옵션" 참조가 없어야 함).

- [ ] **Step 3: 빌드 검증**

Run: `cd C:\Users\LHJ\AI_Master\frontend; npm run build`
Expected: 빌드 성공. `useGraph`/`useLlm` 미사용 경고/에러 없음.

- [ ] **Step 4: 커밋**

```bash
git add frontend/src/App.tsx
git commit -m "feat: 실행 옵션 체크박스 제거(항상 graph+llm)"
```

---

### Task 7: 샘플메일 명확화 + 스타일 관리 UI + 배지 (#1, #4)

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getStyleMails`, `saveStyleMail`, `GuideResponse.style_used/style_sources` (Task 5).

- [ ] **Step 1: import·상태 추가**

`App.tsx` 상단 import에서 `./api`의 named import 목록에 `getStyleMails`, `saveStyleMail`를 추가한다. 컴포넌트 상태에 추가:
```typescript
  const [styleCount, setStyleCount] = useState(0);
  const [styleInput, setStyleInput] = useState("");
```
그리고 최초 로드 `useEffect`에 스타일 개수 조회를 추가:
```typescript
  useEffect(() => {
    getStyleMails().then((s) => setStyleCount(s.count)).catch(() => setStyleCount(0));
  }, []);
```

- [ ] **Step 2: 샘플메일 버튼 라벨·안내 수정 (#1)**

`App.tsx` 섹션1의 버튼 행을 교체:
```tsx
          <div className="row">
            <button className="ghost" onClick={loadSampleEmail}>내장 샘플 메일 불러오기</button>
            <button className="ghost" onClick={makeSamples}>샘플 엑셀 생성</button>
          </div>
          <p className="muted">
            ※ '내장 샘플'은 앱에 포함된 예시입니다. 실제 Gmail 메일은 Claude Code가
            Gmail MCP로 필요할 때 가져와 아래 제목/본문에 붙여넣습니다.
          </p>
```

- [ ] **Step 3: 스타일 관리 패널 추가**

`App.tsx` 섹션4의 "작성 가이드와 요청 메일 초안" `ops-panel` 안, `buildGuide` 버튼 위에 추가:
```tsx
            <div className="block">
              <p className="muted">내 과거 발송 스타일 샘플: <b>{styleCount}</b>개</p>
              <textarea
                value={styleInput}
                onChange={(e) => setStyleInput(e.target.value)}
                rows={3}
                placeholder="과거에 보냈던 요청 메일 본문을 붙여넣고 저장하면 초안 톤에 반영됩니다."
              />
              <button
                className="ghost inline"
                onClick={async () => {
                  if (!styleInput.trim()) return;
                  const r = await saveStyleMail("", styleInput.trim());
                  setStyleCount(r.count);
                  setStyleInput("");
                }}
              >
                스타일 샘플로 저장
              </button>
            </div>
```

- [ ] **Step 4: 스타일 반영 배지 추가 (#4)**

`App.tsx`에서 `guide &&` 블록의 `<p><b>{guide.guide.guide_title}</b></p>` 바로 아래에 추가:
```tsx
                {guide.style_used ? (
                  <span className="chip">내 과거 발송 스타일 반영됨 ({guide.style_sources.join(", ")})</span>
                ) : (
                  <span className="chip warn">스타일 샘플 없음 · 기본 톤</span>
                )}
```

- [ ] **Step 5: 빌드 검증**

Run: `cd C:\Users\LHJ\AI_Master\frontend; npm run build`
Expected: 빌드 성공.

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/App.tsx
git commit -m "feat: 내장 샘플 명확화 + 스타일 샘플 관리 UI/배지"
```

---

### Task 8: 제출 추적 문구 명확화 (#5)

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 안내 문구 추가**

`App.tsx` 섹션4 "제출 현황과 리마인드" `ops-panel`의 `<h3>제출 현황과 리마인드</h3>` 바로 아래에 추가:
```tsx
            <p className="muted">
              현재는 파일 식별자 기반 mock 추적입니다. 실제 회신 메일 확인은
              Claude Code의 Gmail MCP로 수행할 수 있습니다(후속 확장).
            </p>
```

- [ ] **Step 2: 빌드 검증**

Run: `cd C:\Users\LHJ\AI_Master\frontend; npm run build`
Expected: 빌드 성공.

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/App.tsx
git commit -m "docs: 제출 추적이 mock/MCP-assisted임을 UI에 명시"
```

---

### Task 9: 문서 업데이트 (시연 대본 · 멘토 설명)

**Files:**
- Modify: `docs/시연영상_대본.md`
- Modify: `docs/기술_설명_멘토용.md`

- [ ] **Step 1: 시연 대본에 MCP 흐름 추가**

`docs/시연영상_대본.md` 끝에 새 섹션 추가:
```markdown
## Gmail MCP 스타일 기반 요청 초안 (신규)

1. (Claude Code) 팀장이 포워딩한 취합 메일을 Gmail MCP로 검색·열람한다.
2. (Claude Code) 내 Sent에서 과거 취합요청 메일 N개를 가져와 /api/save-style-mail로 저장한다.
3. 포워딩 메일 제목/본문을 앱 입력에 붙여넣고 '가이드/메일 초안 생성'을 실행한다.
4. 초안이 '내 과거 발송 스타일 반영됨' 배지와 함께 생성된다.
5. 확인·수정 후 Claude Code가 create_draft로 Gmail 임시보관함에 초안을 저장한다.

핵심: 앱은 Gmail을 직접 읽지 않는다. 읽기/드래프트는 Claude Code(MCP)가 수행하고 앱은 텍스트만 처리한다.
```

- [ ] **Step 2: 멘토 설명에 구분·주의 추가**

`docs/기술_설명_멘토용.md`에 다음 문단을 적절한 위치(RAG/Gmail 관련 섹션)에 추가:
```markdown
### Gmail MCP 스타일 반영 (신규)

- 과거 발송 메일을 모델에 학습시키는 것이 아니라, docs/reference/style_samples에
  저장한 메일을 참고 문서처럼 검색(RAG)해 초안 프롬프트에 톤 예시로 주입한다.
- Gmail 읽기/드래프트 저장은 앱이 아니라 Claude Code가 Gmail MCP로 수행하는
  Human-in-the-loop 방식이다(앱 자동 수신함 감시 아님).
```

- [ ] **Step 3: 커밋**

```bash
git add "docs/시연영상_대본.md" "docs/기술_설명_멘토용.md"
git commit -m "docs: Gmail MCP 스타일 흐름 시연/멘토 설명 반영"
```

---

## 최종 검증 (모든 태스크 후)

- [ ] `.\.venv\Scripts\python.exe -m pytest tests -q` → 45 passed 기대.
- [ ] `cd frontend; npm run build` → 성공.
- [ ] `.\.venv\Scripts\python.exe backend\cli.py demo` → 정상 실행.
- [ ] 과장 금지 문구 점검: 앱 자동 수신함/모델 학습 주장 없는지 문서 확인.

## Self-Review 결과 (계획 작성자)

- **스펙 커버리지:** #1(Task 7 Step2), #3(Task 6), #4(Task 1–5,7), #5(Task 8), 스타일 RAG 코어(Task 1–4), 문서(Task 9), 폴백(Task 1 dir 없음/Task 2 LLM 폴백) 모두 태스크 존재. #2/#6/#7은 스펙상 명시적 범위 밖.
- **Placeholder 스캔:** 모든 코드 스텝에 실제 코드 포함. "적절한 처리" 류 없음.
- **타입 일관성:** `retrieve_style_samples`/`STYLE_DIR`/`_build_style_hint`/`style_used`/`style_sources` 명칭이 Task 1→2→3→4→5→7에서 동일하게 사용됨. 저장·검색 모두 `rag_tools.STYLE_DIR` 단일 참조.
