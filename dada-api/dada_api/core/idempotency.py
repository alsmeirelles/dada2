"""PostgreSQL-backed idempotency middleware for mutating API requests."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dada_api.core.errors import error_response
from dada_api.core.security import decode_access_token
from dada_api.db.session import async_session_factory
from dada_api.models.idempotency import IdempotencyRecord

MUTATING_METHODS = {"POST", "PUT", "PATCH"}


class IdempotencyMiddleware:
    """Replay completed responses for matching idempotency keys."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in MUTATING_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_key = headers.get(b"idempotency-key")
        if raw_key is None:
            await self.app(scope, receive, send)
            return

        key = raw_key.decode("utf-8", errors="replace").strip()
        if not 8 <= len(key) <= 128:
            await self._send_error(
                send,
                400,
                "invalid_idempotency_key",
                "Idempotency-Key must be 8 to 128 characters.",
            )
            return

        body = await self._read_body(receive)
        request_hash = hashlib.sha256(body).hexdigest()
        caller_scope = self._caller_scope(headers.get(b"authorization"))
        method = scope["method"]
        path = scope.get("raw_path", scope["path"].encode()).decode("utf-8")

        record, created = await self._reserve(
            caller_scope, method, path, key, request_hash
        )
        if not created:
            if record.request_hash != request_hash:
                await self._send_error(
                    send,
                    409,
                    "idempotency_conflict",
                    "The idempotency key was already used with a different "
                    "request body.",
                )
                return
            if record.status_code is None:
                await self._send_error(
                    send,
                    409,
                    "idempotency_in_progress",
                    "A request with this idempotency key is still being processed.",
                )
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": record.status_code,
                    "headers": [
                        (
                            b"content-type",
                            (
                                record.response_content_type or "application/json"
                            ).encode(),
                        ),
                        (b"idempotency-replayed", b"true"),
                    ],
                }
            )
            await send(
                {"type": "http.response.body", "body": record.response_body or b""}
            )
            return

        messages: list[Message] = []

        async def capture(message: Message) -> None:
            messages.append(message)

        sent = False
        try:
            await self.app(scope, self._replay_receive(body), capture)
            status_code, response_body, content_type = self._response_parts(messages)
            if status_code < 500:
                await self._complete(
                    record.id, status_code, response_body, content_type
                )
            else:
                await self._remove(record.id)
            for message in messages:
                await send(message)
            sent = True
        finally:
            if not sent:
                await self._remove(record.id)

    @staticmethod
    def _caller_scope(authorization: bytes | None) -> str:
        """Derive a stable user scope without trusting unverified token text."""
        if authorization is None:
            return hashlib.sha256(b"anonymous").hexdigest()
        scheme, _, token = authorization.decode(errors="replace").partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                subject = str(decode_access_token(token)["sub"])
                return hashlib.sha256(f"user:{subject}".encode()).hexdigest()
            except ValueError:
                pass
        return hashlib.sha256(authorization).hexdigest()

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        return b"".join(chunks)

    @staticmethod
    def _replay_receive(body: bytes) -> Receive:
        delivered = False

        async def receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    @staticmethod
    def _response_parts(messages: list[Message]) -> tuple[int, bytes, str | None]:
        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        headers = dict(start.get("headers", []))
        content_type = headers.get(b"content-type")
        return start["status"], body, content_type.decode() if content_type else None

    @staticmethod
    async def _reserve(
        scope: str, method: str, path: str, key: str, request_hash: str
    ) -> tuple[IdempotencyRecord, bool]:
        async with async_session_factory() as session:
            record = IdempotencyRecord(
                scope=scope,
                method=method,
                path=path,
                key=key,
                request_hash=request_hash,
            )
            session.add(record)
            try:
                await session.commit()
                await session.refresh(record)
                return record, True
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.scope == scope,
                        IdempotencyRecord.method == method,
                        IdempotencyRecord.path == path,
                        IdempotencyRecord.key == key,
                    )
                )
                if existing is None:
                    raise
                return existing, False

    @staticmethod
    async def _complete(
        record_id: int, status_code: int, body: bytes, content_type: str | None
    ) -> None:
        async with async_session_factory() as session:
            record = await session.get(IdempotencyRecord, record_id)
            if record is not None:
                record.status_code = status_code
                record.response_body = body
                record.response_content_type = content_type
                record.completed_at = datetime.now(UTC)
                await session.commit()

    @staticmethod
    async def _remove(record_id: int) -> None:
        async with async_session_factory() as session:
            record = await session.get(IdempotencyRecord, record_id)
            if record is not None:
                await session.delete(record)
                await session.commit()

    @staticmethod
    async def _send_error(
        send: Send, status_code: int, code: str, message: str
    ) -> None:
        response = error_response(status_code, code, message)
        await send(
            {
                "type": "http.response.start",
                "status": response.status_code,
                "headers": response.raw_headers,
            }
        )
        await send({"type": "http.response.body", "body": response.body})
