"""Scheduling constants shared by both the app and its DB migrations.

Defined once, here, rather than in Settings/.env, because
APPOINTMENT_DURATION_MINUTES is baked directly into a Postgres DDL
expression at migration time (see
alembic/versions/0003_prevent_overlapping_appointments.py, which imports it
from this module) - a DB constraint can't read runtime config. Changing
either duration value requires a new migration, not just an env var change.
Business hours are equally real-world constants (no clinic is open 24/7),
just not ones that happen to be baked into DDL.
"""

APPOINTMENT_DURATION_MINUTES = 30

# Applied identically to every department (documented simplification - see
# README "Known scope simplifications"; a real system would likely need
# per-department hours).
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18

# Python's date.weekday(): Monday=0 ... Sunday=6.
CLOSED_WEEKDAYS = {6}  # Sunday
