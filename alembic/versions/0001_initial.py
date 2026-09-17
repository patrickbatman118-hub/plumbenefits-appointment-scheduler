"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-17

"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("time", sa.Time(), nullable=False),
        sa.Column("tz", sa.String(length=50), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("raw_text", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("department_id", "date", "time", name="uq_department_slot"),
    )


def downgrade() -> None:
    op.drop_table("appointments")
    op.drop_table("departments")
