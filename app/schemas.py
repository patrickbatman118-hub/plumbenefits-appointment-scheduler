from datetime import date as date_cls
from datetime import time as time_cls
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class OCRResult(BaseModel):
    raw_text: str
    confidence: float = Field(ge=0.0, le=1.0)


class Entities(BaseModel):
    date_phrase: str
    time_phrase: str
    department: str


class EntitiesResult(BaseModel):
    entities: Entities
    entities_confidence: float = Field(ge=0.0, le=1.0)


class EntitiesRequest(BaseModel):
    raw_text: str


class Normalized(BaseModel):
    date: str
    time: str
    tz: str

    # These reach book_appointment's date.fromisoformat()/time.fromisoformat()
    # calls unvalidated otherwise. Without this, POSTing a malformed value
    # directly to /appointments or /normalize (the individual endpoints are
    # meant to be independently callable, per the assignment's own curl/
    # Postman requirement) raises a bare ValueError deep in scheduler.py that
    # the router's `except ValueError` then mislabels as "ambiguous
    # department" - a confusing, wrong guardrail for what's actually a
    # malformed-date problem. Validating here turns it into a proper 422
    # instead.
    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        date_cls.fromisoformat(v)
        return v

    @field_validator("time")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        time_cls.fromisoformat(v)
        return v


class NormalizedResult(BaseModel):
    normalized: Normalized
    normalization_confidence: float = Field(ge=0.0, le=1.0)


class NormalizeRequest(BaseModel):
    entities: Entities


class AppointmentOut(BaseModel):
    department: str
    date: str
    time: str
    tz: str


class AppointmentRequest(BaseModel):
    entities: Entities
    normalized: Normalized


class AppointmentRecord(AppointmentOut):
    id: int
    status: str


class DepartmentsResponse(BaseModel):
    departments: list[str]


class GuardrailResponse(BaseModel):
    status: Literal["needs_clarification"] = "needs_clarification"
    message: str


class ConflictResponse(BaseModel):
    status: Literal["slot_conflict"] = "slot_conflict"
    message: str


class FinalOk(BaseModel):
    appointment: AppointmentOut
    status: Literal["ok"] = "ok"


ScheduleResult = Annotated[
    Union[FinalOk, GuardrailResponse, ConflictResponse],
    Field(discriminator="status"),
]

# EntitiesResult/NormalizedResult have no "status" field to discriminate on
# (matching the spec's own JSON contract for those steps), so these are
# plain unions rather than discriminated ones - Pydantic still resolves them
# unambiguously since each member's required fields are disjoint. Used as
# response_model on /entities and /normalize so the OpenAPI schema actually
# reflects that either shape can come back, instead of documenting only the
# success case.
EntitiesStepResult = Union[EntitiesResult, GuardrailResponse]
NormalizedStepResult = Union[NormalizedResult, GuardrailResponse]


class ScheduleTrace(BaseModel):
    ocr: Optional[OCRResult] = None
    entities: Optional[EntitiesResult] = None
    normalized: Optional[NormalizedResult] = None


class ScheduleResponse(BaseModel):
    trace: ScheduleTrace
    result: ScheduleResult
