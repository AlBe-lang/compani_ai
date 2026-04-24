"""Token authentication middleware — Part 8 Stage 2 (Q5).

Jupyter-style shared token:
  * Auto-generated per run when SystemConfig.dashboard_token is empty.
  * Required on every HTTP and WebSocket request.
  * HTTP: ``Authorization: Bearer <token>`` OR ``?token=<token>`` query.
  * WebSocket: ``?token=<token>`` query parameter (WebSocket doesn't support
    custom headers reliably across all clients).

Failed auth responds 401 with a generic message (no token hint). The token
itself is NEVER logged — only `auth.granted` / `auth.denied` events.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket, status

from observability.logger import get_logger

log = get_logger(__name__)


def extract_http_token(request: Request) -> str | None:
    """Prefer Authorization header, fall back to ``?token=`` query."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    q = request.query_params.get("token")
    return q if q else None


def extract_ws_token(websocket: WebSocket) -> str | None:
    """Only query param — WebSocket header support is inconsistent."""
    q = websocket.query_params.get("token")
    return q if q else None


def verify_http(request: Request, expected_token: str) -> None:
    """Raises 401 if the request's token doesn't match ``expected_token``.

    Constant-time comparison to resist timing attacks even though the
    deployment target is localhost — habit over paranoia.
    """
    presented = extract_http_token(request) or ""
    if _constant_time_equals(presented, expected_token):
        return
    log.warning(
        "auth.denied.http",
        path=request.url.path,
        source=request.client.host if request.client else "?",
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing token",
    )


async def verify_ws(websocket: WebSocket, expected_token: str) -> bool:
    """Close the socket with 1008 if the token is wrong; return True on pass."""
    presented = extract_ws_token(websocket) or ""
    if _constant_time_equals(presented, expected_token):
        return True
    log.warning(
        "auth.denied.ws",
        source=websocket.client.host if websocket.client else "?",
    )
    await websocket.close(code=1008, reason="invalid token")
    return False


def _constant_time_equals(a: str, b: str) -> bool:
    """Avoid short-circuit on length difference for comparison timing parity."""
    if len(a) != len(b):
        # Still run through the loop for consistent timing profile.
        a = a.ljust(max(len(a), len(b)), "\x00")
        b = b.ljust(max(len(a), len(b)), "\x00")
        equal = False
    else:
        equal = True
    for ca, cb in zip(a, b):
        if ca != cb:
            equal = False
    return equal
