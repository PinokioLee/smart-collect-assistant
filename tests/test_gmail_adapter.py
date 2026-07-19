"""GmailReadAdapter 실제 읽기·파싱 경로 검증.

OAuth 자격증명 없이도 '실제 Gmail 응답 형식(format=full)'을 그대로 흉내 낸 가짜
서비스로 어댑터의 list_new()·_parse() 를 검증한다. 즉 credentials.json 만 넣으면
실제 Gmail 에서도 동일하게 동작함을 코드 경로 수준에서 보장한다.
"""

import base64

from smart_collect.tools.inbox_tools import GmailReadAdapter
from smart_collect.tools.mail_classifier import classify_heuristic


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


# 실제 Gmail API users().messages().get(format='full') 응답 형식
_MSG = {
    "id": "18f0a1b2c3d4e5f6",
    "threadId": "18f0a1b2c3d4e5f6",
    "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
    "internalDate": "1752451200000",  # ms epoch → 2025-07-14 (KST 근사)
    "payload": {
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "팀 리더 <lead@company.com>"},
            {"name": "To", "value": "me@company.com"},
            {"name": "Cc", "value": "영업 담당 <sales@company.com>, qa@company.com"},
            {"name": "Subject", "value": "[요청] 7월 시스템 개선 요청사항 취합"},
            {"name": "Date", "value": "Mon, 14 Jul 2025 09:00:00 +0900"},
        ],
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain",
                     "body": {"data": _b64("작성 항목은 부서명, 담당자, 긴급도입니다.\n7월 15일까지 회신 바랍니다.")}},
                    {"mimeType": "text/html",
                     "body": {"data": _b64("<p>html 버전</p>")}},
                ],
            },
            {
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "filename": "개선요청_양식.xlsx",
                "body": {"attachmentId": "ANGjdJ_xxx", "size": 10240},
            },
        ],
    },
}

_LISTING = {"messages": [{"id": _MSG["id"], "threadId": _MSG["threadId"]}]}


class _Exec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class _Messages:
    def __init__(self, listing, msgs):
        self._listing, self._msgs = listing, msgs

    def list(self, **kwargs):
        assert kwargs.get("userId") == "me"
        return _Exec(self._listing)

    def get(self, userId, id, format):  # noqa: A002 - Gmail API 시그니처
        assert format == "full"
        return _Exec(self._msgs[id])

    def attachments(self):
        return _Attachments()


class _Attachments:
    def get(self, userId, messageId, id):  # noqa: A002
        return _Exec({"data": _b64("fake xlsx bytes")})


class _Users:
    def __init__(self, m):
        self._m = m

    def messages(self):
        return self._m


class _FakeService:
    """Gmail API 서비스 객체의 호출 표면(users().messages().list/get)을 흉내."""

    def __init__(self, listing, msgs):
        self._u = _Users(_Messages(listing, msgs))

    def users(self):
        return self._u


def _adapter_with_fake(attachment_dir=None):
    ad = GmailReadAdapter(
        credentials_file="dummy", token_file="dummy", attachment_dir=attachment_dir
    )
    ad._service = lambda: _FakeService(_LISTING, {_MSG["id"]: _MSG})  # OAuth 우회
    return ad


def test_list_new_reads_and_parses_real_shape(tmp_path):
    msgs = _adapter_with_fake(tmp_path).list_new(max_results=5)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.id == "18f0a1b2c3d4e5f6"
    assert m.sender == "팀 리더 <lead@company.com>"
    assert m.to == ["me@company.com"]
    assert m.cc == ["영업 담당 <sales@company.com>", "qa@company.com"]
    assert m.subject == "[요청] 7월 시스템 개선 요청사항 취합"
    assert "부서명, 담당자, 긴급도" in m.body       # base64 본문 디코딩
    assert "html 버전" not in m.body                 # text/plain 만 취함
    assert m.attachments == ["개선요청_양식.xlsx"]   # 중첩 파트에서 첨부 추출
    assert "INBOX" in m.labels
    assert m.received_at.startswith("2025-07-1")     # internalDate → 날짜 변환


def test_parsed_message_classifies_as_collection(tmp_path):
    m = _adapter_with_fake(tmp_path).list_new()[0]
    result = classify_heuristic(m)
    assert result.label == "취합업무메일"
    assert result.intent == "request"
    assert result.tier == "auto"  # 실제 형식 메일도 분류 경로가 동일하게 동작


def test_real_shape_attachment_is_downloaded_for_resend(tmp_path):
    message = _adapter_with_fake(tmp_path).list_new()[0]
    assert len(message.attachment_paths) == 1
    path = tmp_path / message.id / "개선요청_양식.xlsx"
    assert path.exists()
    assert path.read_bytes() == b"fake xlsx bytes"


def test_html_only_message_is_converted_to_visible_text():
    payload = {
        "mimeType": "text/html",
        "body": {
            "data": _b64(
                "<html><head><style>.x{display:none}</style></head>"
                "<body><p>부서별 실적을 취합합니다.</p><div>7월 30일까지 회신 바랍니다.</div></body></html>"
            )
        },
    }
    body, attachments = GmailReadAdapter._extract_body_and_attachments(payload)
    assert "부서별 실적을 취합합니다." in body
    assert "7월 30일까지 회신 바랍니다." in body
    assert "display:none" not in body
    assert attachments == []
