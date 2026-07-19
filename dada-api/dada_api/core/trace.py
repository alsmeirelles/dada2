"""Per-request trace context and middleware."""

import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

trace_id_context: ContextVar[str | None] = ContextVar("trace_id", default=None)
TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


class TraceMiddleware:
    """Attach a safe trace identifier to request context and responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        proposed = headers.get(b"x-trace-id", b"").decode("ascii", errors="ignore")
        trace_id = proposed if TRACE_ID_PATTERN.fullmatch(proposed) else str(uuid4())
        token = trace_id_context.set(trace_id)

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-trace-id", trace_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            trace_id_context.reset(token)
