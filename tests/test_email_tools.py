"""Email Adapter 테스트.

실제 Gmail 발송은 OAuth 자격증명이 필요하므로 자동 테스트에서는 mock adapter 와
API 입력 검증을 확인한다.
"""

from fastapi.testclient import TestClient

from api import app
from smart_collect.tools.email_tools import EmailSendRequest, MockEmailAdapter


def test_mock_email_adapter_records_send():
    adapter = MockEmailAdapter()
    result = adapter.send(
        EmailSendRequest(
            to=["a@example.com", "b@example.com"],
            subject="테스트 발송",
            body="본문",
        )
    )
    assert result.status == "mock_sent"
    assert result.mode == "mock"
    assert result.recipients == ["a@example.com", "b@example.com"]
    assert result.message_id and result.message_id.startswith("MOCK-")


def test_send_email_api_requires_recipient():
    client = TestClient(app)
    res = client.post(
        "/api/send-email",
        json={"to": [], "subject": "제목", "body": "본문"},
    )
    assert res.status_code == 400
    assert "수신자" in res.json()["detail"]


def test_send_email_api_mock_success():
    client = TestClient(app)
    res = client.post(
        "/api/send-email",
        json={
            "to": ["a@example.com"],
            "subject": "취합 요청",
            "body": "작성 후 회신 부탁드립니다.",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "mock_sent"
    assert data["mode"] == "mock"
    assert data["recipients"] == ["a@example.com"]
