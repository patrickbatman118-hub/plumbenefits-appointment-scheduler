"""seed canonical departments

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

DEPARTMENTS = [
    "Dentistry",
    "Cardiology",
    "General Medicine",
    "Dermatology",
    "ENT",
    "Orthopedics",
]


def upgrade() -> None:
    departments_table = sa.table(
        "departments",
        sa.column("canonical_name", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        departments_table,
        [{"canonical_name": name, "is_active": True} for name in DEPARTMENTS],
    )


def downgrade() -> None:
    names = ",".join(f"'{name}'" for name in DEPARTMENTS)
    op.execute(f"DELETE FROM departments WHERE canonical_name IN ({names})")
