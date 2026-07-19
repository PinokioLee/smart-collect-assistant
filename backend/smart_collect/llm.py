"""Azure OpenAI 어댑터 (사내 게이트웨이 SKAX/ai-talentlab 호환).

사용자 제공 패턴(openai.AzureOpenAI)을 그대로 사용한다. 키가 없거나 호출이
실패하면 None 을 반환해 호출부가 휴리스틱으로 폴백하도록 한다.
전체 기능(메일 분석, 가이드 생성 등)이 공유하는 공용 LLM 헬퍼를 제공한다.
"""

from __future__ import annotations

import json
from typing import Any, Optional

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


def chat_json(
    messages: list[dict],
    *,
    schema_name: str,
    schema: dict[str, Any],
    temperature: float = 0.0,
) -> Optional[dict]:
    """JSON Schema 기반 Structured Output을 요청하고 안전하게 폴백한다.

    Azure 배포 모델이 ``json_schema``를 지원하면 strict schema를 사용한다. 구형
    배포는 ``json_object``로, 그것도 지원하지 않으면 일반 응답+JSON 파싱으로
    폴백한다. 어느 경로든 최종 반환값은 JSON object로 제한한다.
    """
    client = get_client()
    if client is None:
        return None

    request = {
        "model": settings.azure_deployment,
        "messages": messages,
        "temperature": temperature,
    }
    formats: list[dict | None] = [
        {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
        {"type": "json_object"},
        None,
    ]
    for response_format in formats:
        try:
            kwargs = dict(request)
            if response_format is not None:
                kwargs["response_format"] = response_format
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if not content:
                continue
            data = _extract_json(content)
            if isinstance(data, dict):
                return data
        except Exception:  # 지원하지 않는 응답 형식/일시 오류는 다음 경로로 폴백
            continue
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


_PLAN_SYSTEM_PROMPT = """당신은 엑셀 취합 워크플로우의 Supervisor Agent입니다.
메일에서 추출한 요구사항과 실제 업로드된 엑셀의 컬럼을 보고, 검증 전략을 '계획'하세요.
당신은 검증을 직접 수행하지 않습니다. 규칙 엔진(결정론 코드)이 실제 검증을 하며,
당신은 어떤 점을 주의해서 검증할지 판단·설명하는 역할입니다.

JSON 으로만 응답하세요:
- strategy: "strict" | "balanced" | "loose" (양식 드리프트 위험이 크면 balanced/loose 권장)
- required_focus: 반드시 필수로 봐야 할 컬럼명 배열
- drift_columns: 메일엔 있으나 실제 파일에 없는 컬럼(과잉 필수규칙 위험) 배열
- risks: 예상 리스크 한 줄 문자열 배열 (예: "긴급도 코드값 표기 흔들림 가능")
- rationale: 이 계획을 택한 이유 한 줄
JSON 외 텍스트는 출력하지 마세요."""

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string", "enum": ["strict", "balanced", "loose"]},
        "required_focus": {"type": "array", "items": {"type": "string"}},
        "drift_columns": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["strategy", "required_focus", "drift_columns", "risks", "rationale"],
    "additionalProperties": False,
}


def plan_collection(
    req: "ExtractedRequirements", actual_columns: list[str]
) -> Optional[dict]:
    """Supervisor(LLM) 실행 계획. Azure 불가 시 None(휴리스틱 폴백)."""
    data = chat_json(
        [
            {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"요청 제목: {req.request_title}\n제출 기한: {req.deadline}\n"
                    f"메일에서 추출한 작성 항목: {', '.join(req.required_fields) or '(없음)'}\n"
                    f"주의사항: {'; '.join(req.cautions) or '(없음)'}\n"
                    f"실제 업로드 엑셀 컬럼: {', '.join(actual_columns) or '(없음)'}"
                ),
            },
        ],
        schema_name="collection_plan",
        schema=_PLAN_SCHEMA,
    )
    if not isinstance(data, dict):
        return None
    return {
        "strategy": data.get("strategy") or "balanced",
        "required_focus": data.get("required_focus") or [],
        "drift_columns": data.get("drift_columns") or [],
        "risks": data.get("risks") or [],
        "rationale": data.get("rationale") or "",
    }


_CORRECTION_SYSTEM_PROMPT = """당신은 엑셀 검증 오류를 '교정 제안'하는 Self-Correction Agent입니다.
당신은 값을 직접 확정하지 않습니다. 당신의 제안은 결정론 코드가 허용값·날짜형식으로
재검증한 뒤에만 채택됩니다. 따라서 정직하게, 확신이 없으면 제안하지 마세요.

규칙:
- 날짜 형식 오류: 값을 YYYY-MM-DD 로 정규화한 제안을 내세요. 날짜로 해석 불가하면 제안 생략.
- 허용되지 않은 코드값: 주어진 allowed 목록 중 의미가 가장 가까운 값 하나로 제안하세요.
  의미가 불명확하면 제안하지 마세요(빈 문자열).
- 필수값 누락·중복은 데이터를 지어내야 하므로 절대 제안하지 마세요.

입력은 오류 목록입니다. 각 오류에 대한 제안을 corrections 배열에 담은 JSON object로 응답하세요:
{"corrections":[{"id": <오류 id>, "suggested": "<제안값 또는 빈 문자열>", "rationale": "<한 줄 근거>"}]}
JSON 외 텍스트는 출력하지 마세요."""

_CORRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "suggested": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["id", "suggested", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["corrections"],
    "additionalProperties": False,
}


def propose_corrections(errors: list[dict]) -> Optional[dict[int, dict]]:
    """LLM 이 오류별 교정값을 '제안'한다. Azure 불가 시 None.

    errors: [{id, error_type, column, value, allowed:[...]}]
    반환: {id: {"suggested": str, "rationale": str}}
    """
    if not errors:
        return {}
    lines = []
    for e in errors:
        allowed = e.get("allowed") or []
        lines.append(
            f'{{"id": {e["id"]}, "error_type": "{e["error_type"]}", '
            f'"column": "{e.get("column")}", "value": "{e.get("value")}", '
            f'"allowed": {allowed}}}'
        )
    data = chat_json(
        [
            {"role": "system", "content": _CORRECTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "다음 오류별 교정 제안을 corrections 배열에 담으세요.\n[\n"
                    + ",\n".join(lines)
                    + "\n]"
                ),
            },
        ],
        schema_name="correction_proposals",
        schema=_CORRECTION_SCHEMA,
    )
    if not isinstance(data, dict) or not isinstance(data.get("corrections"), list):
        return None
    arr = data["corrections"]
    out: dict[int, dict] = {}
    for item in arr:
        try:
            out[int(item["id"])] = {
                "suggested": str(item.get("suggested", "")).strip(),
                "rationale": str(item.get("rationale", "")).strip(),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _extract_json_array(text: str) -> Optional[list]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("["):]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


_TEMPLATE_SYSTEM_PROMPT = """당신은 회사 내부 '취합 양식(엑셀)'을 설계하는 Template Design Agent입니다.
담당자가 자연어로 "이런 걸 걷고 싶다"고 말하면, 걷을 엑셀의 컬럼 구조를 설계하세요.
당신은 양식을 직접 확정하지 않습니다 — 사용자가 검토·수정한 뒤 확정하며,
당신의 설계는 그대로 회신 검증 규칙으로 변환됩니다. 그러니 명확하고 실무적으로 설계하세요.

JSON 으로만 응답하세요:
{
  "title": "양식 제목",
  "purpose": "취합 목적 한 줄",
  "columns": [
    {
      "name": "컬럼명",
      "dtype": "text|date|number|code",
      "required": true|false,
      "allowed_values": ["코드값1","코드값2"],   // dtype=code 일 때만, 아니면 []
      "date_format": "YYYY-MM-DD",                // dtype=date 일 때
      "example": "예시값",
      "description": "작성 안내 한 줄"
    }
  ],
  "duplicate_keys": ["중복 판정에 쓸 컬럼명들"],
  "notes": ["작성 주의사항"]
}
규칙:
- 날짜성 항목(일자/기간/마감)은 dtype=date.
- 값이 정해진 보기 중 하나여야 하는 항목(상태/등급/구분/긴급도 등)은 dtype=code 로 하고 allowed_values 를 채우세요.
- 금액/수량은 dtype=number.
- 사람을 식별하거나 취합 키가 되는 항목(번호/담당자/부서 등)은 required=true 권장.
- 컬럼은 3~10개 범위로 실무적으로 설계. JSON 외 텍스트는 출력하지 마세요."""

_TEMPLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "purpose": {"type": "string"},
        "columns": {
            "type": "array",
            "minItems": 3,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dtype": {"type": "string", "enum": ["text", "date", "number", "code"]},
                    "required": {"type": "boolean"},
                    "allowed_values": {"type": "array", "items": {"type": "string"}},
                    "date_format": {"type": "string"},
                    "example": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": [
                    "name", "dtype", "required", "allowed_values",
                    "date_format", "example", "description",
                ],
                "additionalProperties": False,
            },
        },
        "duplicate_keys": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "purpose", "columns", "duplicate_keys", "notes"],
    "additionalProperties": False,
}


def design_template_with_llm(intent: str) -> Optional[dict]:
    """자연어 취합 의도 → 양식 컬럼 스키마(dict). Azure 불가/실패 시 None(휴리스틱 폴백)."""
    data = chat_json(
        [
            {"role": "system", "content": _TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": f"걷고 싶은 내용(자연어):\n{intent}"},
        ],
        schema_name="collection_template",
        schema=_TEMPLATE_SCHEMA,
        temperature=0.2,
    )
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
        return None
    return data


def analyze_email_with_llm(subject: str, body: str) -> Optional[ExtractedRequirements]:
    """Azure OpenAI 로 메일을 분석한다. 불가하면 None."""
    schema = {
        "type": "object",
        "properties": {
            "request_title": {"type": ["string", "null"]},
            "purpose": {"type": ["string", "null"]},
            "deadline": {"type": ["string", "null"]},
            "required_fields": {"type": "array", "items": {"type": "string"}},
            "cautions": {"type": "array", "items": {"type": "string"}},
            "missing_info": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "request_title", "purpose", "deadline", "required_fields",
            "cautions", "missing_info",
        ],
        "additionalProperties": False,
    }
    data = chat_json(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"메일 제목:\n{subject}\n\n메일 본문:\n{body}"},
        ],
        schema_name="collection_requirements",
        schema=schema,
    )
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
