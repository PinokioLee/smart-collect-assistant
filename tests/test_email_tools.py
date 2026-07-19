"""Email Adapter 테스트.

실제 Gmail 발송은 OAuth 자격증명이 필요하므로 자동 테스트에서는 mock adapter 와
API 입력 검증을 확인한다.
"""

from fastapi.testclient import TestClient

from api import app
from smart_collect.tools.email_tools import (
    EmailSendRequest, GmailApiEmailAdapter, MockEmailAdapter,
)


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


def test_gmail_reply_preserves_thread_headers_and_thread_id():
    captured = {}

    class Request:
        def execute(self):
            return {"id": "SENT-1", "threadId": "THREAD-1"}

    class Messages:
        def send(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class Users:
        def messages(self):
            return Messages()

    class Service:
        def users(self):
            return Users()

    adapter = GmailApiEmailAdapter(credentials_file="unused", token_file="unused")
    adapter._service = lambda: Service()
    request = EmailSendRequest(
        to=["asker@company.com"], subject="Re: 작성 문의", body="마감은 17시입니다.",
        thread_id="THREAD-1", in_reply_to="<question-1@company.com>",
        references="<request-1@company.com>",
    )
    message = adapter._build_message(request)
    assert message["In-Reply-To"] == "<question-1@company.com>"
    assert "<request-1@company.com>" in message["References"]
    assert "<question-1@company.com>" in message["References"]
    result = adapter.send(request)
    assert captured["body"]["threadId"] == "THREAD-1"
    assert result.thread_id == "THREAD-1"
