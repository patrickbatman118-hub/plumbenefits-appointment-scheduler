# AI-Powered Appointment Scheduler Assistant

Backend service that turns a natural-language or photographed appointment request
("Book dentist next Friday at 3pm") into a structured, conflict-checked booking.
Built for the SDE Intern take-home assignment (Problem Statement 1: OCR → Entity
Extraction → Normalization).

## Stack

Python 3.11 · FastAPI · PostgreSQL 18 (Docker) · SQLAlchemy (async) · Alembic ·
Google Gemini API · Docker Compose · `uv` for dependency/venv management ·
minimal HTML/vanilla-JS frontend.

## Architecture

```
                text ──┐
                        ├─► Step 1: OCR/Text Extraction ──► raw_text, confidence
       photo of note ──┘         (Gemini, image only)
                                        │
                                        ▼
                          Step 2: Entity Extraction ──► date_phrase, time_phrase,
                          (Gemini, structured output,       department, confidence
                           department constrained to
                           an enum from the DB)
                                        │
                                        ▼
                          Step 3: Normalization ──► ISO date, time, tz
                          (deterministic: dateparser +
                           zoneinfo — NOT the LLM)
                                        │
                                        ▼
                          Step 4: Book Appointment ──► persisted row
                          (Postgres, UNIQUE constraint on
                           department+date+time)
                                        │
                                        ▼
                              final JSON: ok / needs_clarification / slot_conflict
```

Every stage is both an individual endpoint (matching the spec's JSON contracts
exactly) and part of one composed `/api/v1/schedule` call that chains all four
and returns the full trace — see "API Usage" below.

## Design Decisions (read this before the interview)

These are the choices that go beyond "call an LLM and format the output." Each
one has a one-sentence defense.

1. **The LLM never computes the final date.** Gemini only extracts the *phrase*
   ("next Friday", "3pm"). A deterministic library, `dateparser`, resolves that
   phrase to an ISO date/time, seeded with the real current time in
   `Asia/Kolkata`. *Why:* LLMs are unreliable at date arithmetic and give
   different answers on different calls for the same phrase; a deterministic
   resolver is auditable, unit-testable (`tests/test_normalize.py`), and free.

2. **The LLM cannot hallucinate a department.** The entity-extraction call uses
   Gemini's structured-output mode (`response_schema`) with the `department`
   field typed as a dynamically-built enum: the exact list of department names
   currently in the `departments` table, plus a `"unclear"` sentinel
   (`app/gemini_client.py::build_entities_schema`). *Why:* it is schema-impossible
   for the model to return a department that doesn't exist in the system — no
   post-hoc fuzzy matching or string cleanup needed. If you're asked "how do
   you stop the LLM from making up a department?", this is the answer.

3. **Real conflict-checked booking that accounts for appointment duration, not
   just exact-time dupes.** Every appointment is assumed to occupy a fixed
   `APPOINTMENT_DURATION_MINUTES = 30` block (the spec doesn't define a
   duration, so this is a documented assumption). A plain
   `UNIQUE(department_id, date, time)` constraint only catches two bookings
   at the *exact same minute* — it would happily let someone book 15:15 when
   15:00–15:30 is already taken. Instead, `appointments` has a Postgres
   **GiST EXCLUDE constraint**
   (`alembic/versions/0003_prevent_overlapping_appointments.py`):
   `EXCLUDE USING gist (department_id WITH =, tsrange(date+time, date+time+interval '30 minutes') WITH &&)`.
   This is Postgres's native tool for "no two rows may have overlapping
   ranges for the same key," enforced atomically on every `INSERT` — no
   application-level overlap-checking code, no race condition between a
   check and a write. Booking any overlapping time returns a distinct
   `slot_conflict` status instead of silently double-booking. *Why extend
   the spec's two-state contract:* a real scheduler has to prevent
   double-booking, and range overlap (not just exact-time equality) is what
   "double-booking" actually means once appointments have a duration.

   One SQLAlchemy quirk worth knowing: this constraint isn't declared as a
   `UniqueConstraint`/`ExcludeConstraint` on the `Appointment` model — the
   model's docstring explains why (the migration is the only source of
   truth, since this project never calls `Base.metadata.create_all()`).

4. **Confidence numbers are honestly caveated, not dressed up.** OCR and
   entity-extraction confidence are self-reported by Gemini in the prompt —
   they are **not calibrated probabilities**. This is stated here explicitly
   rather than presented as a real metric. A production version would
   cross-check against something with a real confidence signal (e.g. a
   traditional OCR engine's word-level confidences, or self-consistency
   across repeated calls).

5. **A real `dateparser` bug, worked around and documented.** `dateparser`
   1.4.3 fails to parse `"next Friday"` or `"this Friday"` as a single phrase
   (it returns `None`), even though it parses `"Friday"` alone and
   `"next week"` alone just fine — found while writing the unit tests, not in
   any changelog. `normalize.py` retries with the leading `next`/`this`/`coming`
   stripped and relies on `PREFER_DATES_FROM="future"` to still pick the
   correct upcoming weekday. This also happens to be the least-surprising
   resolution of "next Friday"'s inherent ambiguity (nearest Friday vs. one
   week out) since it always resolves to the closest future occurrence.

6. **A real Postgres 18 image-layout change, worked around and documented.**
   The official `postgres:18` Docker image restructured how it stores data on
   disk (major-version-specific subdirectories, to support `pg_ctlcluster`
   -style upgrades) and now expects the volume mounted at
   `/var/lib/postgresql`, not the pre-18 `/var/lib/postgresql/data`. Mounting
   at the old path makes the container start but fail its healthcheck with
   an explicit error in `docker logs`. Found by actually running
   `docker compose up` and reading the failure, not by reading changelogs
   first — `docker-compose.yml`'s volume mount reflects the fix.

7. **Known scope simplifications** (deliberate, for a 3-day assignment):
   - One resource per department (no multiple doctors/rooms/time-of-day
     capacity) — booking a slot occupies the whole department for that
     department+date+time.
   - Department matching is a fixed, seeded list (`alembic/versions/0002_seed_departments.py`),
     not a self-service admin CRUD.
   - No auth — single-tenant demo, as implied by the spec.

## Project layout

```
app/
  main.py               FastAPI app + static frontend mount
  config.py              Settings (.env via pydantic-settings)
  db.py                   Async SQLAlchemy engine/session
  models.py               Department, Appointment (+ unique slot constraint)
  schemas.py               Pydantic request/response models (spec-exact JSON shapes)
  gemini_client.py         Gemini SDK wrapper (OCR call, entity-extraction call)
  guardrails.py             needs_clarification / slot_conflict response builders
  services/
    ocr.py                  text passthrough vs image OCR
    entities.py              entity extraction
    normalize.py             deterministic date/time resolution (pure function)
    scheduler.py              department lookup, conflict-checked persistence
  routers/
    pipeline.py               /ocr /entities /normalize /appointments /schedule
    departments.py             /departments
alembic/                     migrations (schema + seed data)
static/index.html             minimal frontend
tests/                        unit tests (normalize + guardrails, no DB/network)
```

## Setup

### Run with Docker (recommended — this is what gets demoed)

1. `cp .env.example .env` and fill in `GEMINI_API_KEY` (get one from Google AI Studio).
2. `docker compose up --build`
   - This starts Postgres 18, waits for it to be healthy, then starts the API.
   - The API image is built with `uv` (see `Dockerfile`): `uv sync --frozen`
     installs the exact versions pinned in `uv.lock` into the image's venv,
     then `entrypoint.sh` runs `uv run alembic upgrade head` before starting
     `uv run uvicorn`, so the schema and seed departments are always in place.
3. Open `http://localhost:8000` for the frontend, or use the API directly at
   `http://localhost:8000/api/v1/...`. Interactive API docs at
   `http://localhost:8000/docs`.

If port `5432` is already taken by a local Postgres install, change the host
side of `db`'s port mapping in `docker-compose.yml` (e.g. `"15432:5432"`) —
the API always talks to `db:5432` over the internal Docker network regardless
of what's published to the host.

### Local dev environment (without Docker)

This project uses [`uv`](https://docs.astral.sh/uv/) for the venv and all
dependency management — no `requirements.txt`, no manual `pip install`.

```bash
uv sync                    # creates .venv/ and installs every pinned dependency (incl. dev group)
uv run python -m pytest    # run the test suite
uv run uvicorn app.main:app --reload   # run the API against a Postgres you point DATABASE_URL at
```

(`uv run python -m pytest`, not bare `uv run pytest` — the latter doesn't add
the project root to `sys.path`, so `import app` fails. Tests cover
`normalize.py` and `guardrails.py` only — pure functions, no network or DB
required, so they run without a Gemini key or Postgres.)

## API Usage

### Composed pipeline (what the frontend uses)

```bash
curl -X POST http://localhost:8000/api/v1/schedule \
  -F "text=Book dentist next Friday at 3pm"
```

With an image instead of text:

```bash
curl -X POST http://localhost:8000/api/v1/schedule \
  -F "image=@note.jpg"
```

Successful response shape:

```json
{
  "trace": {
    "ocr": {"raw_text": "Book dentist next Friday at 3pm", "confidence": 1.0},
    "entities": {"entities": {"date_phrase": "next Friday", "time_phrase": "3pm", "department": "Dentistry"}, "entities_confidence": 0.9},
    "normalized": {"normalized": {"date": "2025-09-26", "time": "15:00", "tz": "Asia/Kolkata"}, "normalization_confidence": 0.9}
  },
  "result": {
    "appointment": {"department": "Dentistry", "date": "2025-09-26", "time": "15:00", "tz": "Asia/Kolkata"},
    "status": "ok"
  }
}
```

Ambiguous department:

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book someone next Friday at 3pm"
# result.status == "needs_clarification"
```

Ambiguous date/time:

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist whenever works"
# result.status == "needs_clarification"
```

Double-booking the exact same slot:

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 3pm"
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 3pm"
# second call: result.status == "slot_conflict"
```

Booking a *different* but overlapping time (each appointment occupies a
30-minute block, so 15:15 collides with an existing 15:00 booking even
though the times aren't identical):

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 3pm"
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 3:15pm"
# second call: result.status == "slot_conflict"

curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 4pm"
# this one succeeds: result.status == "ok" (4:00-4:30 doesn't overlap 3:00-3:30)
```

### Individual pipeline steps

```bash
# Step 1
curl -X POST http://localhost:8000/api/v1/ocr -F "text=Book dentist next Friday at 3pm"

# Step 2
curl -X POST http://localhost:8000/api/v1/entities \
  -H "Content-Type: application/json" \
  -d '{"raw_text": "Book dentist next Friday at 3pm"}'

# Step 3
curl -X POST http://localhost:8000/api/v1/normalize \
  -H "Content-Type: application/json" \
  -d '{"entities": {"date_phrase": "next Friday", "time_phrase": "3pm", "department": "Dentistry"}}'

# Step 4
curl -X POST http://localhost:8000/api/v1/appointments \
  -H "Content-Type: application/json" \
  -d '{
        "entities": {"date_phrase": "next Friday", "time_phrase": "3pm", "department": "Dentistry"},
        "normalized": {"date": "2025-09-26", "time": "15:00", "tz": "Asia/Kolkata"}
      }'
```

### Supporting endpoints

```bash
curl http://localhost:8000/api/v1/departments
curl http://localhost:8000/api/v1/appointments
```

## Guardrails summary

| Condition | Response |
|---|---|
| OCR confidence below threshold | `{"status": "needs_clarification", ...}` |
| Department not in the canonical list (`"unclear"`) | `{"status": "needs_clarification", ...}` |
| Entity confidence below threshold | `{"status": "needs_clarification", ...}` |
| Date/time phrase unparsable | `{"status": "needs_clarification", ...}` |
| Requested time overlaps an existing booking for that department | `{"status": "slot_conflict", ...}` (extension, see Design Decisions #3) |
| Gemini API error/timeout | HTTP 502 with a plain error message |
| Oversized/non-image upload | HTTP 413 / 400 |

## Known limitations

- Self-reported LLM confidence is a heuristic (see Design Decisions #4).
- Fixed 30-minute appointment duration for every department (see Design
  Decisions #3) — a real system would need per-department or per-visit-type
  durations, which would mean storing duration per row instead of baking a
  single constant into the DB constraint.
- Single resource per department; no per-doctor/room scheduling.
- No auth/multi-tenancy — out of scope for this assignment.
