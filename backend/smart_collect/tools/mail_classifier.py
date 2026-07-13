"""메일 분류기 — 일반 메일 vs 취합 요청 메일 (확신도 3단계).

설계 원칙
--------
- LLM 이 오분류할 수 있으므로 '자동 발송'은 절대 하지 않는다(Human-in-the-loop).
- 확신도 구간으로 처리 방식을 나눈다.
    auto    (>= 0.75): 취합 요청으로 자동 분류하고 요청 메일 초안 생성
    review  (0.45~0.75): '확인 필요'로 표시(사람이 판단)
    general (< 0.45): 일반 메일
- Azure 키가 없어도 동작하도록 결정론 휴리스틱을 기본 경로로 둔다.
  (LLM 은 보조 판단; 실패 시 휴리스틱으로 폴백.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .inbox_tools import InboxMessage

# 확신도 구간 임계값
AUTO_THRESHOLD = 0.75
REVIEW_THRESHOLD = 0.45

# 취합 요청 신호 키워드 → 가중치(결정론)
_SIGNAL_WEIGHTS: dict[str, float] = {
    "취합": 0.35,
    "제출": 0.25,
    "회신": 0.2,
    "마감": 0.2,
    "기한": 0.2,
    "양식": 0.2,
    "작성 항목": 0.3,
    "작성항목": 0.3,
    "필수": 0.15,
    "요청": 0.12,
    "협조": 0.12,
    "첨부": 0.12,
}
# 일반 메일 신호(취합 요청 점수를 낮춤)
_NEGATIVE_WEIGHTS: dict[str, float] = {
    "뉴스레터": 0.4,
    "구독": 0.3,
    "회식": 0.35,
    "동호회": 0.3,
    "광고": 0.4,
    "안내드립니다": 0.1,
}


@dataclass
class ClassificationResult:
    label: str          # "취합요청" | "일반"
    tier: str           # auto | review | general
    confidence: float
    reasons: list[str] = field(default_factory=list)
    source: str = "rule"  # rule | llm

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "tier": self.tier,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "source": self.source,
        }


def _tier_for(confidence: float) -> tuple[str, str]:
    """확신도 → (tier, label)."""
    if confidence >= AUTO_THRESHOLD:
        return "auto", "취합요청"
    if confidence >= REVIEW_THRESHOLD:
        return "review", "취합요청"
    return "general", "일반"


def classify_heuristic(msg: InboxMessage) -> ClassificationResult:
    """결정론 키워드 기반 분류(재현 가능, 무비용)."""
    text = f"{msg.subject}\n{msg.body}"
    score = 0.0
    reasons: list[str] = []

    for kw, w in _SIGNAL_WEIGHTS.items():
        if kw in text:
            score += w
            reasons.append(f"+{kw}")
    for kw, w in _NEGATIVE_WEIGHTS.items():
        if kw in text:
            score -= w
            reasons.append(f"-{kw}")

    # 엑셀 첨부는 취합 요청의 강한 신호
    if any(a.lower().endswith((".xlsx", ".xls")) for a in msg.attachments):
        score += 0.3
        reasons.append("+엑셀첨부")

    confidence = round(max(0.0, min(score, 1.0)), 2)
    tier, label = _tier_for(confidence)
    return ClassificationResult(
        label=label, tier=tier, confidence=confidence,
        reasons=reasons, source="rule",
    )


def classify_message(
    msg: InboxMessage, *, prefer_llm: bool = True
) -> ClassificationResult:
    """메일을 분류한다. Azure 준비 시 LLM 판단, 아니면/실패 시 휴리스틱.

    LLM 은 확신도만 보정하고, 구간(tier) 판정은 동일한 임계값으로 결정론 처리한다.
    """
    if prefer_llm:
        try:
            from ..config import settings

            if settings.azure_ready:
                llm_res = _classify_with_llm(msg)
                if llm_res is not None:
                    return llm_res
        except Exception:  # noqa: BLE001 - 폴백 보장
            pass
    return classify_heuristic(msg)


def _classify_with_llm(msg: InboxMessage) -> ClassificationResult | None:
    """LLM 으로 취합 요청 여부와 확신도를 판단한다(실패 시 None)."""
    import json

    from ..llm import chat

    prompt = (
        "당신은 사내 메일 분류기입니다. 아래 메일이 '여러 담당자에게 자료 작성을 "
        "요청해 취합해야 하는 취합 요청 메일'인지 판단하세요.\n"
        "JSON 으로만 응답: {is_collection: true|false, confidence: 0~1, reason: string}\n\n"
        f"제목: {msg.subject}\n첨부: {', '.join(msg.attachments) or '없음'}\n본문:\n{msg.body[:1500]}"
    )
    content = chat([{"role": "user", "content": prompt}], temperature=0.0)
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        data = json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None

    conf = float(data.get("confidence", 0.0))
    if not data.get("is_collection", False):
        conf = min(conf, REVIEW_THRESHOLD - 0.01)  # 취합 아님 → auto 로 못 올라감
    conf = round(max(0.0, min(conf, 1.0)), 2)
    tier, label = _tier_for(conf)
    reason = str(data.get("reason", "")).strip()
    return ClassificationResult(
        label=label, tier=tier, confidence=conf,
        reasons=[reason] if reason else [], source="llm",
    )
