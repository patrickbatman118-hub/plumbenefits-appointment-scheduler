"""Guardrail response builders.

Two states come from the spec (`needs_clarification`, `ok`); `slot_conflict`
is an intentional extension for the real booking behaviour this project adds
on top of the spec (see README "Design Decisions" #3).
"""

from app.schemas import ConflictResponse, GuardrailResponse


def ambiguous_department() -> GuardrailResponse:
    return GuardrailResponse(message="Ambiguous or unrecognized department")


def ambiguous_date_time(reason: str = "Ambiguous date/time or department") -> GuardrailResponse:
    return GuardrailResponse(message=reason)


def low_confidence(stage: str, confidence: float, threshold: float) -> GuardrailResponse:
    return GuardrailResponse(
        message=f"{stage} confidence {confidence:.2f} is below the required threshold {threshold:.2f}"
    )


def slot_conflict(department: str, date: str, time: str) -> ConflictResponse:
    return ConflictResponse(
        message=(
            f"{department} already has an appointment that overlaps {date} {time} "
            "(each appointment occupies a 30-minute block)"
        )
    )
