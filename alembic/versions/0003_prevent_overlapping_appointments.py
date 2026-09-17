"""prevent overlapping appointments per department, not just exact-time dupes

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17

"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Every appointment is assumed to occupy this many minutes. The spec doesn't
# define an appointment duration, so this is a documented simplifying
# assumption (see README "Design Decisions"). It's baked into the DB
# constraint expression below, not read from app config at request time -
# changing it requires a new migration.
APPOINTMENT_DURATION_MINUTES = 30


def upgrade() -> None:
    # btree_gist lets a GiST index/exclusion constraint use "=" on a plain
    # integer column (department_id) alongside the range-overlap operator.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # The old exact-match UNIQUE(department_id, date, time) only caught two
    # bookings at literally the same minute. A real appointment occupies a
    # block of time, so booking 15:15 when 15:00-15:30 is already taken must
    # also be rejected. An EXCLUDE constraint is Postgres's native tool for
    # "no two rows may have overlapping ranges for the same key" - enforced
    # atomically by the database itself on every INSERT, so it's race-safe
    # under concurrent requests with no application-level locking needed.
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
