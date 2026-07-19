"""로깅 및 선택적 Langfuse 추적.

기본: Console + File 로그.
USE_LANGFUSE=true 이고 키가 있으면 Langfuse Trace/Generation 도 기록 (선택).

Generation 계측은 이벤트(취합 메일 1건) 단위로 하나의 Trace를 열고, 그 안에서
Supervisor/Worker가 호출하는 개별 LLM 요청(프롬프트 원문 · 응답 · 토큰 · 지연)을
Generation으로 붙인다. ``start_trace``로 연 Trace가 있으면 그 안에 중첩되고,
없으면(예: 파이프라인 단발 호출) 최상위 Generation으로 기록되어 항상 안전하다.
"""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .config import LOG_DIR, ensure_dirs, settings

_LOGGER_NAME = "smart_collect"
_configured = False
_langfuse_client: Any = None
_current_trace: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "smart_collect_langfuse_trace", default=None
)


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


def _get_langfuse_client() -> Any:
    """프로세스당 1개만 만드는 Langfuse 클라이언트. 준비 안 되면 None."""
    global _langfuse_client
    if not settings.langfuse_ready:
        return None
    if _langfuse_client is None:
        try:
            from langfuse import Langfuse

            _langfuse_client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception:  # noqa: BLE001
            get_logger().warning("Langfuse 클라이언트 초기화 실패 - 무시하고 진행")
            return None
    return _langfuse_client


@contextmanager
def start_trace(
    name: str, *, trace_id: str | None = None, metadata: dict[str, Any] | None = None
) -> Iterator[Optional[Any]]:
    """이벤트(취합 메일 1건) 단위 Langfuse Trace를 연다.

    이 컨텍스트 안에서 실행되는 ``llm.chat``/``llm.chat_json`` 호출은 별도 배선 없이
    자동으로 이 Trace의 하위 Generation으로 붙는다(``_current_trace`` 컨텍스트변수).
    Langfuse가 꺼져 있거나 실패해도 본 흐름은 항상 진행된다(None을 yield).
    """
    client = _get_langfuse_client()
    if client is None:
        yield None
        return
    token = None
    try:
        trace = client.trace(id=trace_id, name=name, metadata=metadata or {})
        token = _current_trace.set(trace)
        yield trace
    except Exception:  # noqa: BLE001
        get_logger().warning("Langfuse trace 생성 실패 - 무시하고 진행")
        yield None
    finally:
        if token is not None:
            _current_trace.reset(token)
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass


def log_generation(
    name: str,
    *,
    model: str,
    messages: list[dict],
    output: Any,
    started: float,
    usage: Any = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """LLM 호출 1건(프롬프트 원문·응답·토큰·지연)을 Langfuse Generation으로 기록한다.

    활성 Trace(``start_trace``)가 있으면 그 하위로, 없으면 최상위 Generation으로
    기록한다. Langfuse 미설정/실패는 조용히 무시하고 본 흐름을 막지 않는다.
    """
    if not settings.langfuse_ready:
        return
    client = _get_langfuse_client()
    if client is None:
        return
    try:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        usage_details = None
        if usage is not None:
            usage_details = {
                "input": getattr(usage, "prompt_tokens", None),
                "output": getattr(usage, "completion_tokens", None),
                "total": getattr(usage, "total_tokens", None),
            }
        target = _current_trace.get() or client
        target.generation(
            name=name,
            model=model,
            input=messages,
            output=output,
            metadata={"latency_ms": latency_ms, **(metadata or {})},
            usage=usage_details,
            level="ERROR" if error else "DEFAULT",
            status_message=error,
        )
    except Exception:  # noqa: BLE001
        get_logger().warning("Langfuse generation 기록 실패 - 무시하고 진행")
