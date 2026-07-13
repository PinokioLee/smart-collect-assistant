"""Inbox Read Adapter 도구 — 수신함 수집(읽기).

발송(email_tools.py)과 동일하게 Mock/Gmail 두 어댑터를 같은 인터페이스로 제공한다.
  - MockInboxAdapter   : 내장 샘플 수신함(자격증명 없이 실행/테스트/시연)
  - GmailReadAdapter   : Gmail API(gmail.readonly)로 실제 수신함 읽기

EMAIL_READ_MODE=gmail + GMAIL_CREDENTIALS_FILE 설정 시 실제 Gmail 을 읽는다.
분류/초안/큐 로직은 어느 어댑터를 쓰든 동일하게 동작한다.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..config import settings

GMAIL_READ_SCOPE = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class InboxMessage:
    """수신함 메일 1건(분류·분석 입력)."""

    id: str
    sender: str
    subject: str
    body: str
    received_at: str = ""
    attachments: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    thread_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "subject": self.subject,
            "body": self.body,
            "received_at": self.received_at,
            "attachments": self.attachments,
            "labels": self.labels,
        }


class InboxAdapter(Protocol):
    def list_new(self, max_results: int = 20) -> list[InboxMessage]:
        """새 수신 메일 목록을 반환한다(최신순)."""


# ---------------------------------------------------------------------------
# Mock 수신함 — 자격증명 없이 전체 파이프라인을 돌리기 위한 샘플
# ---------------------------------------------------------------------------

_MOCK_INBOX: list[InboxMessage] = [
    InboxMessage(
        id="MOCK-INBOX-001",
        sender="team-lead@company.com",
        subject="[요청] 2026년 7월 시스템 개선 요청사항 취합",
        body=(
            "각 부서별 시스템 개선 요청사항을 첨부 양식에 작성하여 "
            "2026년 7월 15일 17시까지 회신 바랍니다.\n"
            "작성 항목은 부서명, 담당자, 요청시스템, 개선요청내용, 긴급도, 요청사유, 요청일자입니다.\n"
            "긴급도는 상/중/하 중 하나로 작성해 주세요.\n"
            "부서명, 담당자, 요청시스템, 긴급도는 필수 입력 항목입니다."
        ),
        received_at="2026-07-13 09:12",
        attachments=["개선요청_양식.xlsx"],
        labels=["INBOX"],
    ),
    InboxMessage(
        id="MOCK-INBOX-002",
        sender="hr@company.com",
        subject="7월 인원 현황 및 초과근무 자료 제출 요청",
        body=(
            "다음 주까지 각 팀에서 7월 인원 현황과 초과근무 현황을 취합하여 제출해 주세요.\n"
            "제출 기한: 2026년 7월 18일 까지. 첨부된 양식을 작성해 회신 부탁드립니다."
        ),
        received_at="2026-07-13 10:03",
        attachments=["월간인원현황.xlsx"],
        labels=["INBOX"],
    ),
    InboxMessage(
        id="MOCK-INBOX-003",
        sender="welfare@company.com",
        subject="[사내] 7월 직원 회식 및 동호회 안내",
        body=(
            "안녕하세요. 7월 부서 회식과 사내 동호회 모집을 안내드립니다.\n"
            "참여를 원하시는 분은 게시판을 확인해 주세요. 즐거운 한 주 되세요!"
        ),
        received_at="2026-07-13 11:20",
        attachments=[],
        labels=["INBOX"],
    ),
    InboxMessage(
        id="MOCK-INBOX-004",
        sender="partner@vendor.co.kr",
        subject="자료 관련 문의드립니다",
        body=(
            "안녕하세요, 지난주 회의에서 논의한 자료 제출 건으로 문의드립니다. "
            "관련 항목을 정리하여 회신해 주실 수 있을까요? 요청 내용 확인 부탁드립니다."
        ),
        received_at="2026-07-13 13:41",
        attachments=[],
        labels=["INBOX"],
    ),
    InboxMessage(
        id="MOCK-INBOX-005",
        sender="newsletter@it-news.com",
        subject="이번 주 IT 트렌드 뉴스레터",
        body=(
            "이번 주 주요 IT 소식을 전해드립니다. 구독을 취소하시려면 하단 링크를 클릭하세요."
        ),
        received_at="2026-07-13 08:00",
        attachments=[],
        labels=["INBOX"],
    ),
]


class MockInboxAdapter:
    """내장 샘플 수신함을 반환한다(실제 Gmail 접근 없음)."""

    def list_new(self, max_results: int = 20) -> list[InboxMessage]:
        return list(_MOCK_INBOX[:max_results])


# ---------------------------------------------------------------------------
# Gmail 실제 읽기 — gmail.readonly
# ---------------------------------------------------------------------------


class GmailReadAdapter:
    """Gmail API(gmail.readonly) 기반 실제 수신함 읽기 Adapter."""

    def __init__(
        self,
        *,
        credentials_file: str,
        token_file: str,
        query: str = "in:inbox newer_than:2d",
    ) -> None:
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.query = query

    def list_new(self, max_results: int = 20) -> list[InboxMessage]:
        service = self._service()
        listed = (
            service.users()
            .messages()
            .list(userId="me", q=self.query, maxResults=max_results)
            .execute()
        )
        out: list[InboxMessage] = []
        for meta in listed.get("messages", []):
            full = (
                service.users()
                .messages()
                .get(userId="me", id=meta["id"], format="full")
                .execute()
            )
            out.append(self._parse(full))
        return out

    # --- OAuth 서비스 (읽기 스코프 전용 토큰 파일 사용) ---
    def _service(self):
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                "Gmail OAuth credentials 파일을 찾을 수 없습니다: "
                f"{self.credentials_file}"
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Gmail API 의존성이 설치되지 않았습니다. "
                "`pip install -r backend/requirements.txt`를 다시 실행하세요."
            ) from exc

        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_file), GMAIL_READ_SCOPE
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), GMAIL_READ_SCOPE
                )
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds)

    # --- Gmail 메시지 → InboxMessage 파싱 ---
    @staticmethod
    def _parse(msg: dict) -> InboxMessage:
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        body, attachments = GmailReadAdapter._extract_body_and_attachments(
            msg.get("payload", {})
        )
        received = ""
        ts = msg.get("internalDate")
        if ts:
            try:
                received = datetime.fromtimestamp(int(ts) / 1000).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except (ValueError, OverflowError):
                received = ""
        return InboxMessage(
            id=msg.get("id", ""),
            thread_id=msg.get("threadId", ""),
            sender=headers.get("from", ""),
            subject=headers.get("subject", "(제목 없음)"),
            body=body,
            received_at=received,
            attachments=attachments,
            labels=msg.get("labelIds", []),
        )

    @staticmethod
    def _extract_body_and_attachments(payload: dict) -> tuple[str, list[str]]:
        """MIME 파트를 순회해 본문 텍스트와 첨부 파일명을 수집한다."""
        body_parts: list[str] = []
        attachments: list[str] = []

        def walk(part: dict) -> None:
            filename = part.get("filename")
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if filename:
                attachments.append(filename)
            elif mime == "text/plain" and data:
                try:
                    body_parts.append(
                        base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
                    )
                except (ValueError, UnicodeDecodeError):
                    pass
            for sub in part.get("parts", []) or []:
                walk(sub)

        walk(payload)
        return ("\n".join(body_parts).strip(), attachments)


def get_inbox_adapter() -> InboxAdapter:
    """설정에 따라 수신함 어댑터를 반환한다(기본 mock)."""
    if settings.email_read_mode == "gmail":
        return GmailReadAdapter(
            credentials_file=settings.gmail_credentials_file,
            token_file=settings.gmail_read_token_file,
        )
    return MockInboxAdapter()
