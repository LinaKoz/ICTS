"""Origin check for state-changing requests (CSRF defence in depth).

`SameSite=Lax` already keeps the session cookie off cross-site POSTs, but
"site" ignores ports, so another page on `localhost:<other port>` would
still be same-site. Browsers always send `Origin` on cross-origin and
POST requests, so a request whose `Origin` names a different host:port
than the `Host` it reached is rejected. Requests with no `Origin`
(curl, test clients, server-to-server) are not browser CSRF vectors and
pass.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_BODY = json.dumps(
    {"error": {"code": "CSRF_REJECTED", "message": "cross-origin request rejected", "details": None}}
).encode()


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k: v for k, v in scope["headers"]}
        origin = headers.get(b"origin")
        if origin is not None:
            host = headers.get(b"host", b"").decode("latin-1")
            if origin == b"null" or urlsplit(origin.decode("latin-1")).netloc != host:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(_BODY)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": _BODY})
                return
        await self.app(scope, receive, send)
