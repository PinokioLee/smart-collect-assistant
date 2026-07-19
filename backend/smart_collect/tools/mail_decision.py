"""메일 처리 자율성 판단과 결정론적 발송 정책 게이트.

LLM은 단순/복잡도와 사람 확인 필요성을 제안한다. 최종 외부 발송 허용 여부는
코드가 신뢰도, 요구사항 완전성, 수신자 allow-list, 근거와 첨부 경로를 검증해 결정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from ..state import ExtractedRequirements
from .inbox_tools import InboxMessage
from .mail_classifier import ClassificationResult


@dataclass
class AutonomyDecision:
    action: str = "review"               # auto_send | review | ignore | quarantine
    template_action: str = "review"      # use_attached | generate | review | none
    complexity: str = "complex"          # simple | complex
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    source: str = "policy"               # llm+policy | policy

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "template_action": self.template_action,
            "complexity": self.complexity,
            "reasons": self.reasons,
            "risk_flags": self.risk_flags,
            "source": self.source,
        }


def choose_template_action(
    msg: InboxMessage, req: ExtractedRequirements, *, prefer_llm: bool = True
) -> str:
    excel_names = [
        name for name in msg.attachments
        if name.lower().endswith((".xlsx", ".xls"))
    ]
    text = f"{msg.subject}\n{msg.body}".lower()
    if excel_names and (
        any(k in Path(name).stem.lower() for name in excel_names for k in ("양식", "서식", "template"))
        or any(k in text for k in ("첨부 양식", "첨부한 양식", "양식에 작성", "양식을 작성"))
    ):
        return "use_attached"
    if excel_names and prefer_llm:
        try:
            from ..llm import chat_json

            data = chat_json([{
                "role": "user",
                "content": f"""취합 요청 메일의 Excel 첨부가 담당자에게 다시 보낼 빈 작성 양식인지,
단순 참고자료/기존 데이터인지 판단하세요. JSON만 응답:
{{"template_action":"use_attached|generate|review","reason":"근거"}}
제목: {msg.subject}
첨부명: {excel_names}
본문: {msg.body[:1200]}""",
            }], schema_name="template_action", schema={
                "type": "object",
                "properties": {
                    "template_action": {
                        "type": "string", "enum": ["use_attached", "generate", "review"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["template_action", "reason"],
                "additionalProperties": False,
            }, temperature=0.0)
            if data:
                action = str(data.get("template_action") or "")
                if action in {"use_attached", "generate", "review"}:
                    return action
        except Exception:
            pass
    if excel_names:
        return "review"
    if req.required_fields:
        return "generate"
    return "review"


def _llm_assessment(
    msg: InboxMessage, req: ExtractedRequirements, classification: ClassificationResult
) -> dict | None:
    try:
        from ..llm import chat_json

        data = chat_json(
            [{
                "role": "user",
                "content": f"""당신은 취합업무 Supervisor입니다. 아래 요청을 사람이 확인하지 않고
담당자들에게 작성 요청 메일을 보내도 되는 단순·명확한 업무인지 평가하세요.
정책 변경, 수신자 불명확, 마감/작성항목 누락, 복합 의도, 보안 위험은 반드시 확인이 필요합니다.
JSON만 응답: {{"complexity":"simple|complex","requires_review":true|false,"risk_flags":[],"reason":"근거"}}

분류: {classification.category}/{classification.intent}, 신뢰도={classification.confidence}
제목: {msg.subject}
첨부: {msg.attachments}
마감: {req.deadline}
작성항목: {req.required_fields}
누락정보: {req.missing_info}
본문: {msg.body[:1800]}""",
            }],
            schema_name="autonomy_assessment",
            schema={
                "type": "object",
                "properties": {
                    "complexity": {"type": "string", "enum": ["simple", "complex"]},
                    "requires_review": {"type": "boolean"},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["complexity", "requires_review", "risk_flags", "reason"],
                "additionalProperties": False,
            },
            temperature=0.0,
        )
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def decide_autonomy(
    msg: InboxMessage,
    req: ExtractedRequirements,
    classification: ClassificationResult,
    recipients: list[dict],
    grounding: dict,
    attachment_paths: list[str],
    *,
    auto_send_enabled: bool | None = None,
    prefer_llm: bool = True,
    template_action_override: str | None = None,
) -> AutonomyDecision:
    """LLM 제안 위에 비우회 정책 게이트를 적용한다."""
    enabled = settings.auto_send_enabled if auto_send_enabled is None else auto_send_enabled
    template_action = template_action_override or choose_template_action(
        msg, req, prefer_llm=prefer_llm
    )
    risks = list(dict.fromkeys(classification.risk_flags))
    reasons: list[str] = []

    assessment = _llm_assessment(msg, req, classification) if prefer_llm else None
    source = "llm+policy" if assessment else "policy"
    complexity = str((assessment or {}).get("complexity") or "complex").lower()
    if complexity not in {"simple", "complex"}:
        complexity = "complex"
    if assessment:
        risks.extend(str(x) for x in assessment.get("risk_flags", []) if str(x).strip())
        if assessment.get("reason"):
            reasons.append(str(assessment["reason"]))

    if classification.category == "spam":
        return AutonomyDecision(
            action="quarantine", template_action="none", complexity="complex",
            reasons=reasons or ["스팸·위험메일로 분류됨"],
            risk_flags=list(dict.fromkeys(risks)), source=source,
        )
    if classification.category != "collection":
        return AutonomyDecision(
            action="ignore", template_action="none", complexity=complexity,
            reasons=reasons or ["취합업무가 아님"],
            risk_flags=list(dict.fromkeys(risks)), source=source,
        )
    if classification.intent != "request":
        risks.append(f"unsupported_intent:{classification.intent}")
    if classification.confidence < settings.auto_send_min_confidence:
        risks.append("low_classification_confidence")
    # 받은 양식을 그대로 재사용하는 경우에는 원본 양식 자체가 작성 기준이다.
    # 새 양식을 생성한 경우에는 사람이 컬럼/검증 규칙을 확인한 뒤 발송한다.
    if template_action != "use_attached":
        if not req.deadline:
            risks.append("missing_deadline")
        if not req.required_fields:
            risks.append("missing_required_fields")
        if req.missing_info:
            risks.append("missing_request_information")
    if not recipients:
        risks.append("missing_recipients")

    recipient_emails = [str(r.get("email") or "").strip().lower() for r in recipients]
    if any("@" not in email for email in recipient_emails):
        risks.append("invalid_recipient")
    allowed = settings.auto_send_allowed_domains
    if not allowed:
        risks.append("recipient_allowlist_not_configured")
    elif any(email.rsplit("@", 1)[-1] not in allowed for email in recipient_emails if "@" in email):
        risks.append("recipient_outside_allowlist")

    grounding_flags = grounding.get("flags", []) if isinstance(grounding, dict) else []
    if grounding_flags and template_action != "use_attached":
        risks.append("grounding_incomplete")

    if template_action == "review":
        risks.append("template_undetermined")
    if template_action == "generate":
        risks.append("generated_template_requires_review")
    if template_action in {"use_attached", "generate"}:
        usable = [p for p in attachment_paths if Path(p).exists()]
        if not usable:
            risks.append("attachment_file_unavailable")

    if template_action != "use_attached":
        if assessment and bool(assessment.get("requires_review", False)):
            risks.append("llm_requested_review")
        if complexity != "simple":
            risks.append("complex_request")
    if not enabled:
        risks.append("auto_send_disabled")

    risks = list(dict.fromkeys(risks))
    if risks:
        reasons.append("정책 게이트: " + ", ".join(risks))
        action = "review"
    else:
        action = "auto_send"
        reasons.append("LLM 단순 업무 판단과 모든 안전 정책을 통과함")
    return AutonomyDecision(
        action=action,
        template_action=template_action,
        complexity=complexity,
        reasons=reasons,
        risk_flags=risks,
        source=source,
    )
