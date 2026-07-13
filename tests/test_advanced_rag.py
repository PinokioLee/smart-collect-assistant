"""고급 RAG(Phase B) 회귀 테스트 — 메타데이터/쿼리재작성/재정렬/근거검증."""

from smart_collect.state import ExtractedRequirements
from smart_collect.tools import advanced_rag as ar


def test_parse_frontmatter():
    text = "---\n종류: 가이드\n부서: 공통\n---\n본문입니다"
    meta, body = ar.parse_frontmatter(text)
    assert meta["종류"] == "가이드"
    assert meta["부서"] == "공통"
    assert body.strip() == "본문입니다"


def test_reference_index_loads_with_metadata():
    docs = ar.load_reference_index()
    assert len(docs) >= 5
    titles = {d.title for d in docs}
    assert "엑셀_컬럼_설명서.md" in titles
    doc = next(d for d in docs if d.title == "엑셀_컬럼_설명서.md")
    assert doc.metadata.get("종류") == "양식설명"


def test_query_rewriting_heuristic():
    qs = ar.rewrite_queries("7월 취합 요청", ["부서명", "긴급도"], prefer_llm=False)
    assert "부서명 작성 규칙" in qs
    assert "제출 기한 규칙" in qs
    assert len(qs) <= 6


def test_retrieve_with_metadata_ranks_and_filters():
    qs = ar.rewrite_queries("개선요청 취합", ["부서명", "긴급도", "요청일자"], prefer_llm=False)
    docs = ar.retrieve_with_metadata(qs, top_k=4)
    assert docs, "관련 문서가 검색되어야 한다"
    # 점수 내림차순 정렬
    scores = [d.score for d in docs]
    assert scores == sorted(scores, reverse=True)


def test_metadata_filter_department():
    qs = ["월간 실적 협조 요청", "제출 기한"]
    docs = ar.retrieve_with_metadata(qs, filters={"부서": "생산팀"}, top_k=5)
    # 생산팀 문서 또는 공통 문서만 통과(품질/영업 전용 문서는 없지만 공통은 허용)
    for d in docs:
        dept = d.metadata.get("부서", "")
        assert dept in ("생산팀", "공통")


def test_grounding_all_present():
    req = ExtractedRequirements(
        request_title="취합", deadline="2026-07-15 17:00",
        required_fields=["부서명", "담당자"],
    )
    recipients = [{"name": "김", "dept": "영업팀", "email": "a@b.com"}]
    retrieved = ar.retrieve_with_metadata(["부서명 작성 규칙"], top_k=2)
    report = ar.verify_grounding(req, recipients, retrieved)
    assert report.flags == []
    assert report.score == 1.0


def test_grounding_flags_missing_fields():
    req = ExtractedRequirements(request_title="취합", deadline=None, required_fields=[])
    report = ar.verify_grounding(req, [], [])
    # 작성 항목/제출 기한/담당자/근거 모두 없음 → 4개 flag
    assert "작성 항목" in report.flags
    assert "제출 기한" in report.flags
    assert report.score == 0.0


def test_build_rag_context_shape():
    req = ExtractedRequirements(
        request_title="7월 개선요청 취합", deadline="2026-07-15",
        required_fields=["부서명", "긴급도", "요청일자"],
    )
    recipients = [{"name": "김", "dept": "영업팀", "email": "a@b.com"}]
    ctx = ar.build_rag_context(req, recipients, subject="7월 취합", prefer_llm=False)
    assert ctx["queries"]
    assert isinstance(ctx["sources"], list)
    assert "checks" in ctx["grounding"] and "score" in ctx["grounding"]
