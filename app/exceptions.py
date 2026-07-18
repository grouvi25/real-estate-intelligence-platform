"""Custom application exceptions (TZ section 6.2)."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: Optional[str] = None,
        headers: Optional[dict] = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code or f"ERR_{status_code}"


class NotFoundError(AppException):
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} с id {resource_id} не найден",
            code="NOT_FOUND",
        )


class ForbiddenError(AppException):
    def __init__(self, message: str = "Доступ запрещён"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=message,
            code="FORBIDDEN",
        )


class ValidationError(AppException):
    def __init__(self, field: str, message: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: {message}",
            code="VALIDATION_ERROR",
        )


class AIBudgetExceededError(AppException):
    def __init__(self, message: str = "Превышен дневной лимит расходов на AI"):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
            code="AI_BUDGET_EXCEEDED",
        )


class ConsentRequiredError(AppException):
    def __init__(self, message: str = "Требуется согласие на обработку ПД"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
            code="CONSENT_REQUIRED",
        )


class GeoProtectedError(AppException):
    def __init__(self, city: str, region: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Город {city} ({region}) защищён. Доступна только партнёрская программа.",
            code="GEO_PROTECTED",
        )
