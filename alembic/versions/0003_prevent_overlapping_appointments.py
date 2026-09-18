"""prevent overlapping appointments per department, not just exact-time dupes

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17

"""

from alembic import op

from app.constants import APPOINTMENT_DURATION_MINUTES

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist lets a GiST index/exclusion constraint use "=" on a plain
    # integer column (department_id) alongside the range-overlap operator.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # The old exact-match UNIQUE(department_id, date, time) only caught two
    # bookings at the same minute, not 15:15 overlapping an existing
    # 15:00-15:30 slot. EXCLUDE is Postgres's native "no two rows may have
    # overlapping ranges for the same key" - atomic on every INSERT, no
    # application-level locking needed.
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS uq_department_slot")
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


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_overlapping_department_slots")
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT uq_department_slot UNIQUE (department_id, date, time)"
    )
