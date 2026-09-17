"""Orchestration + persistence for the booking step.

Booking relies on a DB-level GiST EXCLUDE constraint (overlap-aware, not
just exact-time equality, and including a transition buffer) - see
alembic/versions/0003_prevent_overlapping_appointments.py and
0004_add_appointment_buffer.py - to make double-booking detection race-safe
instead of a check-then-write race condition.
"""

from datetime import date as date_type
from datetime import time as time_type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Department
from app.schemas import AppointmentOut, Entities, Normalized


async def list_department_names(db: AsyncSession) -> list[str]:
    result = await db.execute(select(Department.canonical_name).where(Department.is_active.is_(True)))
    return [row[0] for row in result.all()]


async def get_department_by_name(db: AsyncSession, name: str) -> Department | None:
    # Same is_active filter as list_department_names - a deactivated
    # department shouldn't be bookable even if a caller (e.g. a direct
    # /appointments request) supplies its name directly, bypassing the
    # Gemini enum that would otherwise exclude it.
    result = await db.execute(
        select(Department).where(Department.canonical_name == name, Department.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def book_appointment(
    db: AsyncSession, entities: Entities, normalized: Normalized, raw_text: str
) -> AppointmentOut:
    """Raises ValueError if the department doesn't exist, or
    sqlalchemy.exc.IntegrityError if the slot is already booked (caller
    translates both into the appropriate guardrail response)."""
    department = await get_department_by_name(db, entities.department)
    if department is None:
        raise ValueError(f"Unknown department: {entities.department}")

    appointment = Appointment(
        department_id=department.id,
        date=date_type.fromisoformat(normalized.date),
        time=time_type.fromisoformat(normalized.time),
        tz=normalized.tz,
        raw_text=raw_text,
        status="ok",
    )
    db.add(appointment)
    await db.commit()

    return AppointmentOut(
        department=department.canonical_name,
        date=normalized.date,
        time=normalized.time,
        tz=normalized.tz,
    )


async def list_appointments(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Appointment, Department.canonical_name)
        .join(Department, Appointment.department_id == Department.id)
        .order_by(Appointment.date, Appointment.time)
    )
    return [
        {
            "id": appt.id,
            "department": dept_name,
            "date": appt.date.isoformat(),
            "time": appt.time.strftime("%H:%M"),
            "tz": appt.tz,
            "status": appt.status,
        }
        for appt, dept_name in result.all()
    ]
