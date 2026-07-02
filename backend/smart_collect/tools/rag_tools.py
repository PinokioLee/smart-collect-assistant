"""RAG Reference Agent 도구 (선택적).

1차 PoC 정책: RAG 는 필수 기능이 아니다. 작성 항목/코드값 기준이 불명확할 때만
제한적으로 사용한다. FAISS/임베딩이 없는 환경에서도 동작하도록, 기본 구현은
로컬 문서 폴더(docs/reference)에 대한 가벼운 키워드 검색으로 제공한다.
운영 단계에서 FAISS + Azure Embedding 으로 교체할 수 있도록 인터페이스를 고정한다.
"""

from __future__ import annotations

from pathlib import Path

from ..config import ROOT_DIR

REFERENCE_DIR = ROOT_DIR / "docs" / "reference"
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


def retrieve_reference_documents(
    query: str, document_type: str | None = None, top_k: int = 3
) -> dict:
    """질의와 관련된 내부 기준 문서를 검색한다.

    Returns: {retrieved_docs, source_info, confidence_score}
    """
    if not REFERENCE_DIR.exists():
        return {"retrieved_docs": [], "source_info": [], "confidence_score": 0.0}

    terms = [t for t in query.replace("/", " ").split() if t]
    scored: list[tuple[float, str, str]] = []
    for path in REFERENCE_DIR.rglob("*"):
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = sum(text.count(t) for t in terms)
        if hits:
            score = min(hits / (len(terms) or 1) / 5, 1.0)
            scored.append((score, path.name, text[:500]))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    return {
        "retrieved_docs": [{"title": name, "snippet": snip} for _, name, snip in top],
        "source_info": [name for _, name, _ in top],
        "confidence_score": round(top[0][0], 2) if top else 0.0,
    }
