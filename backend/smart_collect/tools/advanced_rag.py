"""고급 RAG (Phase B) — 메타데이터 필터링 · 쿼리 재작성 · 재정렬 · 근거 검증.

설계 방침
--------
- 임베딩/FAISS 없이(표준 라이브러리만) 동작하도록 구성한다. 운영에서 의미검색으로
  확장할 수 있게 인터페이스만 고정한다.
- 핵심은 'RAG 를 많이 쓰는 것'이 아니라, 잘못된 요청 메일이 만들어지지 않도록
  근거를 찾고 검증하는 것이다.

포함 기법
  1) 메타데이터 필터링  : 문서 frontmatter(종류/부서/상태/연도)로 검색 범위 축소
  2) 쿼리 재작성        : 메일/요구사항 → 검색에 적합한 질의 여러 개 생성
  3) 재정렬(rerank)     : 질의 term 겹침 점수로 상위 문서만 선택
  4) 근거 검증(grounding): 생성될 요청 메일의 핵심 항목이 실제 근거를 갖는지 확인
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import ROOT_DIR
from ..state import ExtractedRequirements

REFERENCE_DIR = ROOT_DIR / "docs" / "reference"


@dataclass
class RefDoc:
    title: str
    metadata: dict[str, str]
    body: str
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "metadata": self.metadata,
            "snippet": self.body[:300],
            "score": round(self.score, 3),
        }


# --------------------------------------------------------------------------
# frontmatter 파싱 + 인덱스 로드
# --------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """`--- key: value ---` 형식의 frontmatter 를 파싱한다(YAML 의존성 없음)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    header = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body


def load_reference_index(reference_dir: Path | None = None) -> list[RefDoc]:
    """docs/reference 의 모든 문서를 메타데이터와 함께 로드한다."""
    base = reference_dir or REFERENCE_DIR
    if not base.exists():
        return []
    docs: list[RefDoc] = []
    for path in sorted(base.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_frontmatter(text)
        docs.append(RefDoc(title=path.name, metadata=meta, body=body))
    return docs


# --------------------------------------------------------------------------
# 1) 쿼리 재작성
# --------------------------------------------------------------------------

def rewrite_queries(
    subject: str, fields: list[str], *, prefer_llm: bool = True
) -> list[str]:
    """메일 제목/작성항목을 검색에 적합한 질의 여러 개로 변환한다.

    Azure 준비 시 LLM 으로 생성하고, 아니면/실패 시 결정론 규칙으로 폴백한다.
    """
    if prefer_llm:
        try:
            from ..config import settings

            if settings.azure_ready:
                q = _rewrite_with_llm(subject, fields)
                if q:
                    return q
        except Exception:  # noqa: BLE001 - 폴백 보장
            pass
    return _rewrite_heuristic(subject, fields)


def _rewrite_heuristic(subject: str, fields: list[str]) -> list[str]:
    queries: list[str] = []
    for f in fields[:4]:
        queries.append(f"{f} 작성 규칙")
    queries += ["취합 요청 메일 예시", "제출 기한 규칙", "엑셀 컬럼 설명", "부서 담당자"]
    # 중복 제거(순서 보존)
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:6]


def _rewrite_with_llm(subject: str, fields: list[str]) -> list[str] | None:
    import json

    from ..llm import chat

    prompt = (
        "다음 취합 요청 메일에 대해, 사내 규정·양식·과거 예시를 찾기 위한 "
        "검색 질의 3~5개를 만들어라. JSON 배열로만 응답: [\"질의1\", \"질의2\"]\n\n"
        f"제목: {subject}\n작성 항목: {', '.join(fields)}"
    )
    content = chat([{"role": "user", "content": prompt}], temperature=0.2)
    if not content:
        return None
    s, e = content.find("["), content.rfind("]")
    if s == -1 or e == -1:
        return None
    try:
        arr = json.loads(content[s:e + 1])
    except json.JSONDecodeError:
        return None
    return [str(x).strip() for x in arr if str(x).strip()][:6] or None


# --------------------------------------------------------------------------
# 2) 메타데이터 필터링 + 3) 재정렬
# --------------------------------------------------------------------------

def _matches_filters(meta: dict[str, str], filters: dict[str, str]) -> bool:
    """메타데이터 필터. 값이 '공통'인 문서는 부서 필터를 통과한다."""
    for key, want in filters.items():
        val = meta.get(key, "")
        if key == "부서" and val == "공통":
            continue
        if want not in val and val not in want:
            return False
    return True


def retrieve_with_metadata(
    queries: list[str],
    *,
    filters: dict[str, str] | None = None,
    top_k: int = 4,
    reference_dir: Path | None = None,
) -> list[RefDoc]:
    """메타데이터 필터 + 키워드 겹침 점수로 상위 문서를 반환한다(재정렬 포함)."""
    docs = load_reference_index(reference_dir)
    terms = {t for q in queries for t in q.replace("/", " ").split() if len(t) >= 2}

    ranked: list[RefDoc] = []
    for d in docs:
        if filters and not _matches_filters(d.metadata, filters):
            continue
        haystack = d.body + " " + " ".join(d.metadata.values())
        hits = sum(haystack.count(t) for t in terms)
        if hits <= 0:
            continue
        d.score = min(hits / (len(terms) or 1) / 3, 1.0)
        ranked.append(d)

    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked[:top_k]


# --------------------------------------------------------------------------
# 4) 근거 검증(grounding)
# --------------------------------------------------------------------------

@dataclass
class GroundingReport:
    checks: list[dict] = field(default_factory=list)  # [{item, grounded, source}]
    flags: list[str] = field(default_factory=list)     # 근거 없는 항목
    score: float = 0.0                                  # grounded / total

    def to_dict(self) -> dict:
        return {"checks": self.checks, "flags": self.flags, "score": round(self.score, 2)}


def verify_grounding(
    req: ExtractedRequirements,
    recipients: list[dict],
    retrieved: list[RefDoc],
) -> GroundingReport:
    """생성될 요청 메일의 핵심 항목이 실제 근거를 갖는지 검증한다.

    근거 없는 항목은 flag 로 표시해 사람이 확인하도록 한다(임의 생성 방지).
    """
    checks: list[dict] = []

    def add(item: str, grounded: bool, source: str) -> None:
        checks.append({"item": item, "grounded": grounded, "source": source if grounded else ""})

    add("작성 항목", bool(req.required_fields), "수신 메일 본문")
    add("제출 기한", bool(req.deadline), "수신 메일 본문")
    add("담당자/수신자", bool(recipients), "조직도(디렉터리)")
    add(
        "작성 규칙·표현 근거",
        bool(retrieved),
        retrieved[0].title if retrieved else "",
    )

    flags = [c["item"] for c in checks if not c["grounded"]]
    grounded_n = sum(1 for c in checks if c["grounded"])
    score = grounded_n / len(checks) if checks else 0.0
    return GroundingReport(checks=checks, flags=flags, score=score)


def build_rag_context(
    req: ExtractedRequirements,
    recipients: list[dict],
    *,
    subject: str = "",
    dept_filter: str | None = None,
    prefer_llm: bool = True,
) -> dict:
    """쿼리 재작성 → 검색(메타데이터 필터) → 근거 검증을 한 번에 수행한다.

    Returns: {queries, sources:[title], retrieved:[RefDoc dict], grounding:{...}}
    """
    queries = rewrite_queries(subject or (req.request_title or ""), req.required_fields, prefer_llm=prefer_llm)
    filters = {"부서": dept_filter} if dept_filter else None
    retrieved = retrieve_with_metadata(queries, filters=filters, top_k=4)
    grounding = verify_grounding(req, recipients, retrieved)
    return {
        "queries": queries,
        "sources": [d.title for d in retrieved],
        "retrieved": [d.to_dict() for d in retrieved],
        "grounding": grounding.to_dict(),
    }
