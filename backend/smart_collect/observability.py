"""로깅 및 선택적 Langfuse 추적.

기본: Console + File 로그.
USE_LANGFUSE=true 이고 키가 있으면 Langfuse Trace 도 기록 (선택).
"""

from __future__ import annotations

import logging
from typing import Any

from .config import LOG_DIR, ensure_dirs, settings

_LOGGER_NAME = "smart_collect"
_configured = False


def get_logger() -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    ensure_dirs()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.FileHandler(LOG_DIR / "smart_collect.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _configured = True
    return logger


def trace_execution(
    request_id: str,
    node_name: str,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> str | None:
    """노드 실행을 로그(+선택적 Langfuse)에 기록. trace_id 반환(있으면)."""
    logger = get_logger()
    status = "ERROR" if error else "OK"
    logger.info("[%s] %s (%s)", request_id, node_name, status)

    if not settings.langfuse_ready:
        return None

    try:  # Langfuse 는 선택 — 실패해도 본 흐름에 영향 없음
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        trace = client.trace(name=node_name, metadata={"request_id": request_id})
        trace.span(
            name=node_name,
            input=input_summary or {},
            output=output_summary or {},
            level="ERROR" if error else "DEFAULT",
        )
        return trace.id
    except Exception:  # noqa: BLE001
        logger.warning("Langfuse 기록 실패 - 무시하고 진행")
        return None
