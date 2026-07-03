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


def plan_collection(
    req: "ExtractedRequirements", actual_columns: list[str]
) -> Optional[dict]:
    """Supervisor(LLM) 실행 계획. Azure 불가 시 None(휴리스틱 폴백)."""
    content = chat(
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
        ]
    )
    if content is None:
        return None
    data = _extract_json(content)
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

입력은 오류 목록입니다. 각 오류에 대해 JSON 배열로만 응답하세요:
[{"id": <오류 id>, "suggested": "<제안값 또는 빈 문자열>", "rationale": "<한 줄 근거>"}]
JSON 외 텍스트는 출력하지 마세요."""


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
    content = chat(
        [
            {"role": "system", "content": _CORRECTION_SYSTEM_PROMPT},
            {"role": "user", "content": "[\n" + ",\n".join(lines) + "\n]"},
        ]
    )
    if content is None:
        return None
    arr = _extract_json_array(content)
    if arr is None:
        return None
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
