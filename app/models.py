from datetime import date, datetime, time

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy import Date as SA_Date
from sqlalchemy import Time as SA_Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="department")


class Appointment(Base):
    """No overlap constraint is declared here on purpose.

    Two bookings for the same department must not have overlapping
    [time, time + APPOINTMENT_DURATION_MINUTES) ranges - not just avoid an
    exact-time match. That can't be expressed as a plain SQLAlchemy
    UniqueConstraint, so it's enforced as a Postgres GiST EXCLUDE constraint
    defined directly in alembic/versions/0003_prevent_overlapping_appointments.py.
    This project manages its schema entirely through Alembic migrations
    (nothing calls Base.metadata.create_all()), so that migration - not this
    class - is the actual source of truth for the constraint.
    """

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    date: Mapped[date] = mapped_column(SA_Date, nullable=False)
    time: Mapped[time] = mapped_column(SA_Time, nullable=False)
    tz: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    department: Mapped["Department"] = relationship(back_populates="appointments")
