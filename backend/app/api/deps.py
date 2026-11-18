from __future__ import annotations

from fastapi import HTTPException

from app.core.errors import StudioError


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def bad_request(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


def studio_http(exc: StudioError) -> HTTPException:
    return HTTPException(status_code=400, detail=exc.user_message)
