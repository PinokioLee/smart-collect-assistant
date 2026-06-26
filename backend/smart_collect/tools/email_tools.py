"""Email Adapter 도구.

PoC 기본값은 mock 발송이며, EMAIL_SEND_MODE=gmail 로 설정하면 Gmail API OAuth
흐름을 사용해 실제 메일을 발송한다. 실제 발송은 사용자 승인 이후 호출되는
API에서만 수행하도록 분리한다.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from ..config import settings

GMAIL_SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]


@dataclass
class EmailSendRequest:
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    attachment_paths: list[str] = field(default_factory=list)


@dataclass
class EmailSendResult:
    status: str
    mode: str
    recipients: list[str]
    subject: str
    message_id: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mode": self.mode,
            "recipients": self.recipients,
            "subject": self.subject,
            "message_id": self.message_id,
            "detail": self.detail,
        }


class EmailAdapter(Protocol):
    def send(self, request: EmailSendRequest) -> EmailSendResult:
        """Send an email or record a mock send."""


class MockEmailAdapter:
    """시연/테스트용 Adapter. 실제 메일을 보내지 않는다."""

    def send(self, request: EmailSendRequest) -> EmailSendResult:
        return EmailSendResult(
            status="mock_sent",
            mode="mock",
            recipients=request.to,
            subject=request.subject,
            message_id="MOCK-" + str(abs(hash((tuple(request.to), request.subject)))),
            detail="Mock mode: 실제 Gmail 발송 없이 발송 이력만 생성했습니다.",
        )


class GmailApiEmailAdapter:
    """Gmail API OAuth 기반 실제 발송 Adapter."""

    def __init__(
        self,
        *,
        credentials_file: str,
        token_file: str,
        sender: str = "",
    ) -> None:
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.sender = sender

    def send(self, request: EmailSendRequest) -> EmailSendResult:
        service = self._service()
        message = self._build_message(request)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return EmailSendResult(
            status="sent",
            mode="gmail",
            recipients=request.to,
            subject=request.subject,
            message_id=sent.get("id"),
            detail="Gmail API로 실제 메일을 발송했습니다.",
        )

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
                str(self.token_file), GMAIL_SEND_SCOPE
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), GMAIL_SEND_SCOPE
                )
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds)

    def _build_message(self, request: EmailSendRequest) -> EmailMessage:
        if not request.to:
            raise ValueError("수신자(to)가 1명 이상 필요합니다.")
        msg = EmailMessage()
        msg["To"] = ", ".join(request.to)
        if request.cc:
            msg["Cc"] = ", ".join(request.cc)
        if self.sender:
            msg["From"] = self.sender
        msg["Subject"] = request.subject
        msg.set_content(request.body)

        for raw_path in request.attachment_paths:
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(f"첨부 파일을 찾을 수 없습니다: {path}")
            mime_type, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
            msg.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )
        return msg


def get_email_adapter() -> EmailAdapter:
    if settings.email_send_mode == "gmail":
        return GmailApiEmailAdapter(
            credentials_file=settings.gmail_credentials_file,
            token_file=settings.gmail_token_file,
            sender=settings.gmail_sender,
        )
    return MockEmailAdapter()


def send_email(request: EmailSendRequest) -> dict:
    return get_email_adapter().send(request).to_dict()
