"""Guide Draft Agent 도구 — 작성 가이드 / 요청 메일 초안 / 리마인드 생성.

gpt-4.1(Azure)을 사용하고, 키가 없거나 호출 실패 시 결정론적 템플릿으로 폴백한다.
모든 발송성 산출물은 '초안'까지만 생성한다(실제 발송은 사용자 승인 필요).
"""

from __future__ import annotations

import json

from ..llm import chat
from ..state import ExtractedRequirements


# ---------- 작성 가이드 ----------

def generate_writing_guide(
    req: ExtractedRequirements, references: list[dict] | None = None
) -> dict:
    """작성자용 가이드(쉬운 안내문)를 생성한다.

    Returns: {guide_title, guide_body, field_instructions:[{field, how}]}
    """
    fields = req.required_fields or []
    ref_text = ""
    if references:
        ref_text = "\n참고 문서:\n" + "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')[:120]}" for r in references
        )

    prompt = (
        "당신은 취합 담당자를 돕는 Guide Draft Agent입니다. 아래 요청을 바탕으로 "
        "작성자가 쉽게 이해할 안내문을 작성하세요. 초등학생도 이해할 만큼 쉽게.\n"
        "JSON 으로만 응답: {guide_title, guide_body, field_instructions:[{field, how}]}\n\n"
        f"요청 제목: {req.request_title}\n제출 기한: {req.deadline}\n"
        f"작성 항목: {', '.join(fields)}\n주의사항: {'; '.join(req.cautions)}{ref_text}"
    )
    content = chat([{"role": "user", "content": prompt}], temperature=0.2)
    data = _try_json(content)
    if data and data.get("guide_body"):
        return {
            "guide_title": data.get("guide_title") or f"{req.request_title} 작성 안내",
            "guide_body": data["guide_body"],
            "field_instructions": data.get("field_instructions", []),
        }
    return _guide_fallback(req)


def _guide_fallback(req: ExtractedRequirements) -> dict:
    fields = req.required_fields or []
    instr = [{"field": f, "how": f"{f}을(를) 정확히 입력해주세요."} for f in fields]
    body_lines = [
        "안녕하세요. 첨부된 엑셀 양식에 아래 항목을 작성해주세요.",
        *[f"- {f}: {i['how']}" for f, i in zip(fields, instr)],
        f"제출 기한: {req.deadline or '메일 본문 참조'}",
        "작성 완료 후 회신 부탁드립니다.",
    ]
    return {
        "guide_title": f"{req.request_title or '취합'} 작성 안내",
        "guide_body": "\n".join(body_lines),
        "field_instructions": instr,
    }


# ---------- 요청 메일 초안 ----------

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


# ---------- 미제출자 리마인드 ----------

def generate_reminder_message(
    missing_list: list[dict], deadline: str | None, guide_summary: str = ""
) -> dict:
    """미제출자에게 보낼 재안내(리마인드) 문구를 생성한다."""
    names = ", ".join(m.get("name", "") for m in missing_list)
    prompt = (
        "미제출자에게 보낼 정중한 리마인드 메일 초안을 작성하세요. 압박감 없이 협조 요청 톤. "
        "JSON 으로만 응답: {reminder_mail_subject, reminder_mail_body}\n\n"
        f"제출 기한: {deadline}\n미제출자: {names}\n요약: {guide_summary}"
    )
    content = chat([{"role": "user", "content": prompt}], temperature=0.3)
    data = _try_json(content)
    if data and data.get("reminder_mail_body"):
        return {
            "reminder_mail_subject": data.get("reminder_mail_subject", "[취합 재안내]"),
            "reminder_mail_body": data["reminder_mail_body"],
        }
    return {
        "reminder_mail_subject": "[취합 재안내] 자료 제출 협조 부탁드립니다",
        "reminder_mail_body": (
            "안녕하세요.\n\n요청드린 취합 자료가 아직 제출되지 않아 안내드립니다.\n"
            f"제출 기한: {deadline or '안내 참조'}\n첨부 양식을 작성하여 회신 부탁드립니다. 감사합니다."
        ),
    }


def _try_json(content: str | None) -> dict | None:
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
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None
