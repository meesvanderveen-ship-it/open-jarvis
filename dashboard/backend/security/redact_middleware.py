"""Belt-and-suspenders: redact every JSON response body, even if a router
or service forgets to call redact() itself.
"""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from dashboard.backend.security.redact import redact


class RedactJSONMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body += chunk

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            redacted_body = body
        else:
            redacted_body = json.dumps(redact(payload)).encode("utf-8")

        new_response = Response(
            content=redacted_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        new_response.headers["content-length"] = str(len(redacted_body))
        return new_response
