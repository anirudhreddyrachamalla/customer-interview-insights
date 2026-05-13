"""RFC 7807 problem-details exceptions and FastAPI error handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProblemDetail(HTTPException):
    """An HTTPException that carries an RFC 7807 ``type`` and ``title``.

    ``errors`` is an optional field-level validation list, surfaced as
    the ``errors`` member of the RFC 7807 body (matches the shape
    FastAPI's own ``RequestValidationError`` produces). Each entry
    should look like ``{"loc": ["field_name"], "msg": "...", "type": "..."}``
    so frontends can map messages inline.
    """

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.title = title
        self.type_ = type_
        self.errors = errors


def _problem_response(
    *,
    status_code: int,
    title: str,
    detail: Any,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
    )


async def problem_detail_handler(_: Request, exc: ProblemDetail) -> JSONResponse:
    extra: dict[str, Any] | None = None
    if exc.errors is not None:
        extra = {"errors": jsonable_encoder(exc.errors)}
    return _problem_response(
        status_code=exc.status_code,
        title=exc.title,
        detail=str(exc.detail),
        type_=exc.type_,
        extra=extra,
    )


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _problem_response(
        status_code=exc.status_code,
        title=_default_title(exc.status_code),
        detail=str(exc.detail) if exc.detail is not None else _default_title(exc.status_code),
    )


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Starlette/FastAPI renamed HTTP_422_UNPROCESSABLE_ENTITY to
    # HTTP_422_UNPROCESSABLE_CONTENT; fall back for older versions.
    code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    return _problem_response(
        status_code=code,
        title="Validation Error",
        detail="Request payload failed validation.",
        extra={"errors": jsonable_encoder(exc.errors())},
    )


def _default_title(code: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        415: "Unsupported Media Type",
        422: "Unprocessable Entity",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(code, "HTTP Error")


def register_error_handlers(app: FastAPI) -> None:
    """Wire all RFC 7807 handlers onto a FastAPI app."""
    app.add_exception_handler(ProblemDetail, problem_detail_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
