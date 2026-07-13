"""환경 설정 로더.

`.env` 파일 또는 OS 환경 변수에서 설정을 읽는다.
LLM/RAG/Langfuse 는 키가 없으면 자동으로 mock 또는 OFF 로 동작하도록 설계한다.
(설계서 '환경 변수' 표 기준)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 (.../AI_Master)
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
SAMPLE_DIR = DATA_DIR / "samples"
MERGED_DIR = DATA_DIR / "merged_files"
ERROR_DIR = DATA_DIR / "error_reports"
LOG_DIR = ROOT_DIR / "logs"

# .env 로드 (있으면)
load_dotenv(ROOT_DIR / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Azure OpenAI
    azure_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")
    azure_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

    # Langfuse (선택)
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    # 토글
    use_mock_email: bool = _as_bool(os.getenv("USE_MOCK_EMAIL"), default=True)
    use_langfuse: bool = _as_bool(os.getenv("USE_LANGFUSE"), default=False)
    use_rag: bool = _as_bool(os.getenv("USE_RAG"), default=False)

    # Email sending
    # mock: 실제 발송 없이 발송 이력만 반환 / gmail: Gmail API OAuth 로 실제 발송
    email_send_mode: str = os.getenv("EMAIL_SEND_MODE", "mock").strip().lower()
    # Email reading (수신함 수집)
    # mock: 내장 샘플 수신함 반환 / gmail: Gmail API 로 실제 수신함 읽기(gmail.readonly)
    email_read_mode: str = os.getenv("EMAIL_READ_MODE", "mock").strip().lower()
    gmail_credentials_file: str = os.getenv("GMAIL_CREDENTIALS_FILE", "")
    gmail_token_file: str = os.getenv(
        "GMAIL_TOKEN_FILE", str(DATA_DIR / "gmail_token.json")
    )
    # 읽기 스코프(gmail.readonly)는 발송 토큰과 스코프가 달라 별도 토큰 파일을 쓴다.
    gmail_read_token_file: str = os.getenv(
        "GMAIL_READ_TOKEN_FILE", str(DATA_DIR / "gmail_read_token.json")
    )
    gmail_sender: str = os.getenv("GMAIL_SENDER", "")

    @property
    def gmail_read_ready(self) -> bool:
        """실제 Gmail 수신함 읽기 가능 여부(모드=gmail + credentials 존재)."""
        return self.email_read_mode == "gmail" and bool(self.gmail_credentials_file)

    @property
    def azure_ready(self) -> bool:  # noqa: D401
        """실제 Azure OpenAI 호출 가능 여부."""
        return bool(self.azure_api_key and self.azure_endpoint and self.azure_deployment)

    @property
    def langfuse_ready(self) -> bool:
        return self.use_langfuse and bool(self.langfuse_public_key and self.langfuse_secret_key)


settings = Settings()


def ensure_dirs() -> None:
    """런타임 출력 디렉터리 보장."""
    for d in (DATA_DIR, SAMPLE_DIR, MERGED_DIR, ERROR_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
