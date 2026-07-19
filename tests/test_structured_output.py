"""Azure Structured Output 요청과 구형 배포 폴백 검증."""

from types import SimpleNamespace

from smart_collect import llm


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response))]
        )


def _client(completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_chat_json_requests_strict_json_schema(monkeypatch):
    completions = _Completions(['{"action":"review"}'])
    monkeypatch.setattr(llm, "get_client", lambda: _client(completions))
    result = llm.chat_json(
        [{"role": "user", "content": "판단"}],
        schema_name="decision",
        schema={
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
            "additionalProperties": False,
        },
    )
    assert result == {"action": "review"}
    response_format = completions.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


def test_chat_json_falls_back_to_json_object(monkeypatch):
    completions = _Completions([RuntimeError("unsupported"), '{"action":"review"}'])
    monkeypatch.setattr(llm, "get_client", lambda: _client(completions))
    result = llm.chat_json(
        [{"role": "user", "content": "판단"}],
        schema_name="decision",
        schema={"type": "object"},
    )
    assert result == {"action": "review"}
    assert completions.calls[1]["response_format"] == {"type": "json_object"}
