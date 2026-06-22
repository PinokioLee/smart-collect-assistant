"""Azure OpenAI 어댑터 (Phase 2).

키가 없거나 라이브러리가 없으면 None 을 반환하여 호출부가 휴리스틱으로
폴백하도록 한다. 1차 PoC 에서 LLM 은 '메일 분석' 한 곳에만 쓴다.
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


def _get_client():
    """langchain-openai 의 AzureChatOpenAI 클라이언트. 준비 안 되면 None."""
    if not settings.azure_ready:
        return None
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError:
        return None
    return AzureChatOpenAI(
        api_key=settings.azure_api_key,
        azure_endpoint=settings.azure_endpoint,
        azure_deployment=settings.azure_deployment,
        api_version=settings.azure_api_version,
        temperature=0,
    )


def analyze_email_with_llm(
    subject: str, body: str
) -> Optional[ExtractedRequirements]:
    """Azure OpenAI 로 메일을 분석한다. 불가하면 None."""
    client = _get_client()
    if client is None:
        return None

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"메일 제목:\n{subject}\n\n메일 본문:\n{body}"),
    ]
    response = client.invoke(messages)
    text = response.content if isinstance(response.content, str) else str(response.content)

    # JSON 블록 추출 (```json ... ``` 또는 순수 JSON)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    data = json.loads(text[start : end + 1])
    return ExtractedRequirements(
        request_title=data.get("request_title"),
        purpose=data.get("purpose"),
        deadline=data.get("deadline"),
        required_fields=data.get("required_fields", []) or [],
        cautions=data.get("cautions", []) or [],
        missing_info=data.get("missing_info", []) or [],
    )
