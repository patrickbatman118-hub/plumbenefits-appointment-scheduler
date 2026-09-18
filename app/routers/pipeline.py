from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.gemini_client import GeminiServiceError
from app.guardrails import ambiguous_date_time, ambiguous_department, low_confidence, slot_conflict
from app.services.normalize import DateTimeRejected
from app.schemas import (
    AppointmentRecord,
    AppointmentRequest,
    EntitiesRequest,
    EntitiesStepResult,
    FinalOk,
    Normalized,
    NormalizedResult,
    NormalizedStepResult,
    NormalizeRequest,
    OCRResult,
    ScheduleResponse,
    ScheduleResult,
    ScheduleTrace,
)
from app.services import entities as entities_service
from app.services import idempotency as idempotency_service
from app.services import normalize as normalize_service
from app.services import ocr as ocr_service
from app.services import scheduler as scheduler_service

router = APIRouter(prefix="/api/v1", tags=["pipeline"])
settings = get_settings()

MAX_IMAGE_BYTES = 8 * 1024 * 1024


async def _run_ocr(text: str | None, image: UploadFile | None) -> OCRResult:
    if image is not None:
        content = await image.read()
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image too large (max 8MB)")
        if not (image.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail="Uploaded file must be an image")
        try:
            return await ocr_service.ocr_from_image(content, image.content_type)
        except GeminiServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if text is not None and text.strip():
        return ocr_service.ocr_text(text)
    raise HTTPException(status_code=400, detail="Provide either 'text' or 'image'")


async def _extract_entities(raw_text: str, departments: list[str]):
    try:
        return await entities_service.extract(raw_text, departments)
    except GeminiServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ocr")
async def ocr_endpoint(text: str | None = Form(None), image: UploadFile | None = File(None)) -> OCRResult:
    return await _run_ocr(text, image)


@router.post("/entities", response_model=EntitiesStepResult)
async def entities_endpoint(payload: EntitiesRequest, db: AsyncSession = Depends(get_db)):
    departments = await scheduler_service.list_department_names(db)
    result = await _extract_entities(payload.raw_text, departments)
    if result.entities.department == "unclear":
        return ambiguous_department()
    if result.entities_confidence < settings.entity_confidence_threshold:
        return low_confidence("Entity extraction", result.entities_confidence, settings.entity_confidence_threshold)
    return result


@router.post("/normalize", response_model=NormalizedStepResult)
async def normalize_endpoint(payload: NormalizeRequest):
    try:
        date_str, time_str = normalize_service.normalize_datetime(
            payload.entities.date_phrase, payload.entities.time_phrase
        )
    except DateTimeRejected as exc:
        return ambiguous_date_time(str(exc))
    normalized = Normalized(date=date_str, time=time_str, tz=settings.app_timezone)
    return NormalizedResult(normalized=normalized, normalization_confidence=0.9)


@router.post("/appointments", response_model=ScheduleResult)
async def appointments_endpoint(payload: AppointmentRequest, db: AsyncSession = Depends(get_db)):
    try:
        appointment = await scheduler_service.book_appointment(db, payload.entities, payload.normalized, raw_text="")
    except IntegrityError:
        await db.rollback()
        return slot_conflict(payload.entities.department, payload.normalized.date, payload.normalized.time)
    except ValueError:
        await db.rollback()
        return ambiguous_department()
    return FinalOk(appointment=appointment)


@router.get("/appointments", response_model=list[AppointmentRecord])
async def list_appointments(db: AsyncSession = Depends(get_db)):
    return await scheduler_service.list_appointments(db)


@router.post("/schedule", response_model=ScheduleResponse)
async def schedule_endpoint(
    text: str | None = Form(None),
    image: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> ScheduleResponse:
    """Idempotency-Key is optional and backward compatible - see
    app/services/idempotency.py for what it does and why."""
    req_fingerprint = None
    if idempotency_key:
        image_bytes = await image.read() if image is not None else None
        if image is not None:
            await image.seek(0)  # rewind so _run_ocr can read it again below
        req_fingerprint = idempotency_service.fingerprint(text, image_bytes)

        existing = await idempotency_service.get(db, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != req_fingerprint:
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key was already used with a different request",
                )
            return ScheduleResponse.model_validate(existing.response_body)

    response = await _run_schedule_pipeline(text, image, db)

    if idempotency_key:
        await idempotency_service.store(db, idempotency_key, req_fingerprint, response.model_dump(mode="json"))

    return response


async def _run_schedule_pipeline(
    text: str | None, image: UploadFile | None, db: AsyncSession
) -> ScheduleResponse:
    trace = ScheduleTrace()

    ocr_result = await _run_ocr(text, image)
    trace.ocr = ocr_result
    if ocr_result.confidence < settings.ocr_confidence_threshold:
        return ScheduleResponse(
            trace=trace,
            result=low_confidence("OCR", ocr_result.confidence, settings.ocr_confidence_threshold),
        )

    departments = await scheduler_service.list_department_names(db)
    entities_result = await _extract_entities(ocr_result.raw_text, departments)
    trace.entities = entities_result
    if entities_result.entities.department == "unclear":
        return ScheduleResponse(trace=trace, result=ambiguous_department())
    if entities_result.entities_confidence < settings.entity_confidence_threshold:
        return ScheduleResponse(
            trace=trace,
            result=low_confidence(
                "Entity extraction", entities_result.entities_confidence, settings.entity_confidence_threshold
            ),
        )

    try:
        date_str, time_str = normalize_service.normalize_datetime(
            entities_result.entities.date_phrase, entities_result.entities.time_phrase
        )
    except DateTimeRejected as exc:
        return ScheduleResponse(trace=trace, result=ambiguous_date_time(str(exc)))
    normalized = Normalized(date=date_str, time=time_str, tz=settings.app_timezone)
    trace.normalized = NormalizedResult(normalized=normalized, normalization_confidence=0.9)

    try:
        appointment = await scheduler_service.book_appointment(
            db, entities_result.entities, normalized, raw_text=ocr_result.raw_text
        )
    except IntegrityError:
        await db.rollback()
        return ScheduleResponse(
            trace=trace,
            result=slot_conflict(entities_result.entities.department, normalized.date, normalized.time),
        )
    except ValueError:
        await db.rollback()
        return ScheduleResponse(trace=trace, result=ambiguous_department())

    return ScheduleResponse(trace=trace, result=FinalOk(appointment=appointment))
