"""Azure OpenAI 어댑터 (사내 게이트웨이 SKAX/ai-talentlab 호환).

사용자 제공 패턴(openai.AzureOpenAI)을 그대로 사용한다. 키가 없거나 호출이
실패하면 None 을 반환해 호출부가 휴리스틱으로 폴백하도록 한다.
전체 기능(메일 분석, 가이드 생성 등)이 공유하는 공용 LLM 헬퍼를 제공한다.
"""

from __future__ import annotations

import json
from typing import Optional

from .config import settings
from .state import ExtractedRequirements

_SYSTEM_PROMPT = """당신은 회사 내부 취합 요청 메일을 분석하는 Requirement Analysis Agent입니다.
메일 제목과 본문에서 다음을 추출해 JSON 으로만 응답하세요.
- request_title: 요청 제목 (문자열)
- purpose: 요청 목적 (문자열)
- deadline: 제출 기한 (YYYY-MM-DD HH:MM, 없으면 null)
- required_fields: 작성 항목 목록 (문자열 배열)
- cautions: 주의사항 목록 (문자열 배열)
- missing_info: 메일에서 확인되지 않아 추가 확인이 필요한 항목 (문자열 배열)
추측하지 말고, 본문에 없으면 missing_info 에 넣으세요. JSON 외 다른 텍스트는 출력하지 마세요."""


def get_client():
    """openai.AzureOpenAI 클라이언트. 준비 안 되면 None."""
    if not settings.azure_ready:
        return None
    try:
        from openai import AzureOpenAI
    except ImportError:
        return None
    return AzureOpenAI(
        azure_endpoint=settings.azure_endpoint,
        api_key=settings.azure_api_key,
        api_version=settings.azure_api_version,
    )


def chat(messages: list[dict], *, temperature: float = 0.0) -> Optional[str]:
    """공용 채팅 호출. 응답 문자열 또는 None(폴백)."""
    client = get_client()
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=settings.azure_deployment,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content
    except Exception:  # noqa: BLE001 - 폴백 보장
        return None


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def analyze_email_with_llm(subject: str, body: str) -> Optional[ExtractedRequirements]:
    """Azure OpenAI 로 메일을 분석한다. 불가하면 None."""
    content = chat([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"메일 제목:\n{subject}\n\n메일 본문:\n{body}"},
    ])
    if content is None:
        return None
    data = _extract_json(content)
    if data is None:
        return None
    return ExtractedRequirements(
        request_title=data.get("request_title"),
        purpose=data.get("purpose"),
        deadline=data.get("deadline"),
        required_fields=data.get("required_fields", []) or [],
        cautions=data.get("cautions", []) or [],
        missing_info=data.get("missing_info", []) or [],
    )
