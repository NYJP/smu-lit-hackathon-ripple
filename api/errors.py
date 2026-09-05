"""The section 9 error envelope, shared by every router.

    { "error": { "code": "not_found", "message": "Regulation not found", "details": null } }

`ApiError` is the one exception every router should raise for an
application-level 4xx/5xx. FastAPI's own `HTTPException` (raised internally
for routing failures, e.g. an unknown path) and pydantic's
`RequestValidationError` are also normalised to this same shape by the
handlers registered in `api/main.py`, so every error response — including
validation errors — uses this envelope, never FastAPI's default shape.
"""

from __future__ import annotations

from typing import Any, NoReturn

# Maps a bare HTTP status code to a stable machine-readable error code, used
# when the error did not originate from an ApiError (e.g. a 404 from an
# unmatched route, or a 405 from a wrong method).
_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "external_service_error",
    501: "not_implemented",
    503: "unavailable",
}


def code_for_status(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "error")


def error_envelope(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


class ApiError(Exception):
    """Raise this anywhere in a router or service to produce a section 9
    error response. `status_code` drives the HTTP status; `code` is the
    stable machine-readable string; `message` is the human-readable one;
    `details` is free-form JSON (or None)."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def not_implemented(wave: str) -> NoReturn:
    """Raise the standard 'this arrives later' error for a stubbed route.

    `wave` names the PRD build-order step(s) that introduce this endpoint's
    real behaviour, e.g. "the ingestion & extraction wave (build order
    steps 3 and 5)". A 501 here is an honest statement that the endpoint is
    not built yet — never a fabricated success.
    """
    raise ApiError(
        501,
        "not_implemented",
        f"Not built yet — this endpoint arrives with {wave}.",
    )
