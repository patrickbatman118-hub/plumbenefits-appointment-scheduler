"""Scheduling constants shared by both the app and its DB migrations.

Defined once, here, rather than in Settings/.env, because
APPOINTMENT_DURATION_MINUTES and APPOINTMENT_BUFFER_MINUTES are baked
directly into Postgres DDL expressions at migration time (see
alembic/versions/0003_prevent_overlapping_appointments.py and
0004_add_appointment_buffer.py, which import from this module) - a DB
constraint can't read runtime config. Changing either value requires a new
migration, not just an env var change.

These values aren't arbitrary - they're what every real scheduling tool
researched actually does, cited so they're defensible rather than guessed:
- Calendly: "minimum scheduling notice", "buffer time", "date range" -
  https://calendly.com/help/how-to-fine-tune-your-availability-settings ,
  https://calendly.com/help/how-to-use-buffers
- Cal.com (open source): minimum notice, before/after event buffers,
  future booking limits -
  https://cal.com/blog/mastering-event-level-time-limits-what-lies-beyond-buffer-times
- Google Calendar Appointment Schedules: 1-hour minimum notice floor,
  60-day default booking window -
  https://support.google.com/calendar/answer/10729749
- Clinic scheduling guidance: 10-15 minute buffer between provider
  appointments - https://skiplino.com/blog/best-patient-scheduling-software-for-clinics-hospitals-2025-stop-double-bookings-for-good/
"""

APPOINTMENT_DURATION_MINUTES = 30

# Gap enforced between the end of one appointment and the start of the next
# for the same department - real systems don't just prevent literal overlap,
# they require transition time (see Calendly/Cal.com "buffer time" and the
# clinic-scheduling guidance cited above).
APPOINTMENT_BUFFER_MINUTES = 10

# Can't book something starting in the next few minutes - matches Google
# Calendar's own 1-hour minimum-notice floor.
MIN_BOOKING_NOTICE_MINUTES = 60

# Can't book arbitrarily far in the future (guards against, e.g., a
# misread year from noisy OCR) - matches Google Calendar's default 60-day
# booking window.
MAX_BOOKING_HORIZON_DAYS = 60

# Applied identically to every department (documented simplification - see
# README "Known scope simplifications"; a real system would likely need
# per-department hours).
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18

# Python's date.weekday(): Monday=0 ... Sunday=6.
CLOSED_WEEKDAYS = {6}  # Sunday
