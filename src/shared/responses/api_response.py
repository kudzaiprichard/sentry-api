from __future__ import annotations

from typing import Generic, TypeVar, Optional, List, Dict
from pydantic import BaseModel, model_validator, Field
from math import ceil

T = TypeVar("T")


# ──────────────────────────────────────────────
# ErrorDetail
# ──────────────────────────────────────────────

class ErrorDetail(BaseModel):
    title: str
    code: str
    status: int
    details: Optional[List[str]] = Field(default=None, exclude_none=True)
    field_errors: Optional[Dict[str, List[str]]] = Field(
        default=None, exclude_none=True, alias="fieldErrors"
    )

    class Config:
        populate_by_name = True

    class Builder:
        def __init__(self, title: str, code: str, status: int):
            self._title = title
            self._code = code
            self._status = status
            self._details: List[str] = []
            self._field_errors: Dict[str, List[str]] = {}

        def add_detail(self, detail: str) -> ErrorDetail.Builder:
            self._details.append(detail)
            return self

        def add_field_error(self, field: str, error: str) -> ErrorDetail.Builder:
            self._field_errors.setdefault(field, []).append(error)
            return self

        def add_field_errors(self, field: str, errors: List[str]) -> ErrorDetail.Builder:
            self._field_errors.setdefault(field, []).extend(errors)
            return self

        def build(self) -> ErrorDetail:
            return ErrorDetail(
                title=self._title,
                code=self._code,
                status=self._status,
                details=self._details if self._details else None,
                field_errors=self._field_errors if self._field_errors else None,
            )

    @staticmethod
    def builder(title: str, code: str, status: int) -> ErrorDetail.Builder:
        return ErrorDetail.Builder(title, code, status)

    def has_details(self) -> bool:
        return bool(self.details)

    def has_field_errors(self) -> bool:
        return bool(self.field_errors)


# ──────────────────────────────────────────────
# ApiResponse
# ──────────────────────────────────────────────

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    message: Optional[str] = None
    value: Optional[T] = None
    error: Optional[ErrorDetail] = None

    class Config:
        json_encoders = {None: lambda _: None}

    @model_validator(mode="after")
    def validate_exclusive(self):
        if self.error is not None and self.value is not None:
            raise ValueError("ApiResponse cannot have both error and value")
        return self

    @staticmethod
    def ok(value: T, message: Optional[str] = None) -> ApiResponse[T]:
        return ApiResponse(success=True, message=message, value=value)

    @staticmethod
    def failure(error: ErrorDetail, message: Optional[str] = None) -> ApiResponse[T]:
        return ApiResponse(success=False, message=message, error=error)


# ──────────────────────────────────────────────
# PaginatedResponse
# ──────────────────────────────────────────────

class PaginationInfo(BaseModel):
    page: int
    total: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")

    class Config:
        populate_by_name = True

    @model_validator(mode="before")
    @classmethod
    def compute_total_pages(cls, values):
        page_size = values.get("pageSize") or values.get("page_size")
        total = values.get("total", 0)
        if page_size is not None and page_size <= 0:
            raise ValueError("Page size must be greater than 0")
        if page_size and "totalPages" not in values and "total_pages" not in values:
            values["totalPages"] = ceil(total / page_size)
        return values


class PaginatedResponse(ApiResponse[List[T]], Generic[T]):
    pagination: Optional[PaginationInfo] = None

    @staticmethod
    def ok(
        value: List[T],
        page: int,
        total: int,
        page_size: int,
        message: Optional[str] = None,
    ) -> PaginatedResponse[T]:
        pagination = PaginationInfo(page=page, total=total, pageSize=page_size)
        return PaginatedResponse(
            success=True,
            message=message,
            value=value,
            pagination=pagination,
        )
