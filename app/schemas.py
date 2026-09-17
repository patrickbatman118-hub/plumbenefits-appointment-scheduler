from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class TextInput(BaseModel):
    text: str


class OCRResult(BaseModel):
    raw_text: str
    confidence: float


class Entities(BaseModel):
    date_phrase: str
    time_phrase: str
    department: str


class EntitiesResult(BaseModel):
    entities: Entities
    entities_confidence: float


class EntitiesRequest(BaseModel):
    raw_text: str


class Normalized(BaseModel):
    date: str
    time: str
    tz: str


class NormalizedResult(BaseModel):
    normalized: Normalized
    normalization_confidence: float


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


class ScheduleTrace(BaseModel):
    ocr: Optional[OCRResult] = None
    entities: Optional[EntitiesResult] = None
    normalized: Optional[NormalizedResult] = None


class ScheduleResponse(BaseModel):
    trace: ScheduleTrace
    result: ScheduleResult
