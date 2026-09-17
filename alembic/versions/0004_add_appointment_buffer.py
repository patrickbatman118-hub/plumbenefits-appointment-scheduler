"""add a transition buffer between appointments, not just zero-overlap

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17

"""

from alembic import op

from app.constants import APPOINTMENT_BUFFER_MINUTES, APPOINTMENT_DURATION_MINUTES

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_BLOCKED_MINUTES = APPOINTMENT_DURATION_MINUTES + APPOINTMENT_BUFFER_MINUTES


def upgrade() -> None:
    # 0003 prevented literal overlap (back-to-back bookings with zero gap
    # were allowed). Real scheduling tools require actual transition time
    # between bookings for the same resource (Calendly/Cal.com "buffer
    # time"; clinic-scheduling guidance recommends 10-15 minutes) - see
    # app/constants.py for citations. Widening only the END of each
    # appointment's blocked range by the buffer (not both ends) is what
    # correctly enforces "at least N minutes between this appointment's end
    # and the next one's start" via a single EXCLUDE constraint, without
    # double-counting the gap from both sides.
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_overlapping_department_slots")
    op.execute(
        f"""
        ALTER TABLE appointments
        ADD CONSTRAINT no_overlapping_department_slots
        EXCLUDE USING gist (
            department_id WITH =,
            tsrange(
                (date + time),
                (date + time) + interval '{_BLOCKED_MINUTES} minutes'
            ) WITH &&
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_overlapping_department_slots")
    op.execute(
        f"""
        ALTER TABLE appointments
        ADD CONSTRAINT no_overlapping_department_slots
        EXCLUDE USING gist (
            department_id WITH =,
            tsrange(
                (date + time),
                (date + time) + interval '{APPOINTMENT_DURATION_MINUTES} minutes'
            ) WITH &&
        )
        """
    )
