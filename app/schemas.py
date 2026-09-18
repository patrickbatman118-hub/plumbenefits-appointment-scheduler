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

    # Without this, a malformed value POSTed directly to /appointments or
    # /normalize reaches date.fromisoformat() deep in scheduler.py, whose
    # bare ValueError the router mislabels as "ambiguous department" -
    # validating here turns it into a proper 422 instead.
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

# No "status" field to discriminate on (matches the spec's JSON contract for
# these steps), so plain unions - Pydantic still resolves them unambiguously
# since each member's required fields are disjoint.
EntitiesStepResult = Union[EntitiesResult, GuardrailResponse]
NormalizedStepResult = Union[NormalizedResult, GuardrailResponse]


class ScheduleTrace(BaseModel):
    ocr: Optional[OCRResult] = None
    entities: Optional[EntitiesResult] = None
    normalized: Optional[NormalizedResult] = None


class ScheduleResponse(BaseModel):
    trace: ScheduleTrace
    result: ScheduleResult
