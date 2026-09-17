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
                          (deterministic: dateparser +   validated against:
                           zoneinfo — NOT the LLM)        past/notice/horizon,
                                        │                 business hours, closed days
                                        ▼
                          Step 4: Book Appointment ──► persisted row
                          (Postgres GiST EXCLUDE constraint:
                           overlap- and buffer-aware, not just
                           department+date+time equality)
                                        │
                                        ▼
                              final JSON: ok / needs_clarification / slot_conflict
```

Every stage is both an individual endpoint (matching the spec's JSON contracts
exactly) and part of one composed `/api/v1/schedule` call that chains all four
and returns the full trace — see "API Usage" below. The Gemini calls in steps
1 and 2 are async (don't block the server) and retry transient failures with
backoff; `/schedule` also accepts an optional `Idempotency-Key` header so a
retried request replays the original result instead of re-running the
pipeline — see Design Decisions #6 and #8.

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

3. **Real conflict-checked booking that accounts for appointment duration
   *and* a transition buffer, not just exact-time dupes.** Every appointment
   is assumed to occupy a fixed `APPOINTMENT_DURATION_MINUTES = 30` block
   (the spec doesn't define a duration, so this is a documented assumption).
   A plain `UNIQUE(department_id, date, time)` constraint only catches two
   bookings at the *exact same minute* — it would happily let someone book
   15:15 when 15:00–15:30 is already taken. Instead, `appointments` has a
   Postgres **GiST EXCLUDE constraint**
   (`alembic/versions/0003_prevent_overlapping_appointments.py`, extended by
   `0004_add_appointment_buffer.py`):
   `EXCLUDE USING gist (department_id WITH =, tsrange(date+time, date+time+interval '40 minutes') WITH &&)`
   — 40 = 30 minutes of appointment + a 10-minute transition buffer before
   the next one can start. The buffer isn't guessed: Calendly and Cal.com
   both call this "buffer time," and clinic-scheduling guidance specifically
   recommends a 10-15 minute gap between provider appointments
   ([source](https://skiplino.com/blog/best-patient-scheduling-software-for-clinics-hospitals-2025-stop-double-bookings-for-good/)).
   Widening only the *end* of each appointment's blocked range by the
   buffer (not both ends) is what correctly enforces "at least N minutes
   between this appointment's end and the next one's start" through a
   single EXCLUDE constraint, without double-counting the gap from both
   sides — worth being able to explain the arithmetic here, not just that
   it works. This is Postgres's native tool for "no two rows may
   have overlapping ranges for the same key," enforced atomically on every
   `INSERT` — no application-level overlap-checking code, no race condition
   between a check and a write. Booking any conflicting time returns a
   distinct `slot_conflict` status instead of silently double-booking. *Why
   extend the spec's two-state contract:* a real scheduler has to prevent
   double-booking, and that means both duration overlap and transition time,
   not just exact-time equality. This approach is independently corroborated,
   not just something that happened to work: research into how booking
   systems solve concurrent double-booking specifically names "Postgres
   EXCLUDE USING gist... an exclusion constraint approach provides atomicity
   by construction, where the guarantee lives in the index rather than in a
   query" as the correct database-level solution, over both naive
   check-then-write logic and `SELECT ... FOR UPDATE` locking.

   One SQLAlchemy quirk worth knowing: this constraint isn't declared as a
   `UniqueConstraint`/`ExcludeConstraint` on the `Appointment` model — the
   model's docstring explains why (the migration is the only source of
   truth, since this project never calls `Base.metadata.create_all()`).
   Also worth knowing: `0004` doesn't edit `0003` in place — once a
   migration has run, you add a new one instead of rewriting history, the
   same as you would with any other team's already-applied migration.

4. **Business hours and closed days are enforced — a clinic is not open
   24/7.** This should have been in the design from the start, not added
   after the fact: `app/constants.py` defines `BUSINESS_START_HOUR = 9`,
   `BUSINESS_END_HOUR = 18`, and `CLOSED_WEEKDAYS = {Sunday}`, applied
   identically to every department (documented simplification — a real
   system would likely need per-department hours). `normalize.py` rejects
   any request that resolves to a time outside `09:00–18:00`, a Sunday, or
   an appointment whose 30-minute block would run past closing (e.g.
   17:45 is "during hours" but 17:45–18:15 isn't, so it's rejected too;
   the last bookable slot is 17:30). These constants are intentionally
   shared with the booking-conflict migration (`app/constants.py` is
   imported by both `normalize.py` and
   `alembic/versions/0003_prevent_overlapping_appointments.py`) so the
   appointment duration can't silently drift out of sync between the two
   places that need to agree on it.

5. **Minimum booking notice and a maximum booking horizon — researched
   against how real scheduling tools actually behave, not guessed.**
   Calendly ("minimum scheduling notice", "date range"), Cal.com ("minimum
   notice", "future booking limits"), and Google Calendar's own Appointment
   Schedules feature (1-hour minimum notice floor, 60-day default booking
   window) all enforce both a lower and upper bound on how far from "now" a
   booking can be — not just "must be in the future." `app/constants.py`
   sets `MIN_BOOKING_NOTICE_MINUTES = 60` and `MAX_BOOKING_HORIZON_DAYS = 60`,
   matching Google Calendar's own defaults directly. Without the minimum,
   "book dentist in 30 seconds" would pass the earlier "is this in the
   future" check; without the maximum, a misread year from noisy OCR (e.g.
   "2028" instead of "2026") would silently produce a booking years out
   instead of getting flagged. Sources:
   [Calendly availability settings](https://calendly.com/help/how-to-fine-tune-your-availability-settings),
   [Cal.com time limits](https://cal.com/blog/mastering-event-level-time-limits-what-lies-beyond-buffer-times),
   [Google Calendar Appointment Schedules](https://support.google.com/calendar/answer/10729749).

6. **Gemini calls are truly async, not blocking the server, and retry
   transient failures with backoff.** Two separate findings from actually
   inspecting the SDK and hitting a real failure mid-conversation, not from
   reading docs alone:
   - `google-genai`'s `client.models.generate_content` is a **synchronous,
     blocking** call; `client.aio.models.generate_content` is the real
     coroutine (`inspect.iscoroutinefunction` confirms this directly — True
     for `.aio`, False for the default client). The original version of
     this code called the sync client from inside `async def` FastAPI route
     handlers with no `await`, which blocks the entire single-process event
     loop for the full duration of every Gemini round-trip (often 1-5+
     seconds) — during that window the server can't handle *any* other
     request, not even an unrelated `GET /departments`. Fixed by switching
     to `client.aio`. Proved the fix rather than just asserting it: fired a
     `/schedule` request (2.5s, two Gemini calls) and, 0.3s in, a concurrent
     `GET /departments` — the GET returned in 0.04s instead of waiting for
     the in-flight call.
   - Mid-testing, a real Gemini call failed with `503 UNAVAILABLE - This
     model is currently experiencing high demand`. Google's own
     troubleshooting guidance for 429/503 is "wait and retry with
     exponential backoff"
     ([source](https://ai.google.dev/gemini-api/docs/troubleshooting)).
     `gemini_client.py`'s `_call_with_retry` now does exactly that — up to
     4 attempts, backoff capped at 15s with jitter — but only for
     429/503. A 400 (malformed request) or 401/403 (bad key) will fail
     identically every time, so those raise immediately instead of wasting
     four attempts and several seconds on a guaranteed failure.
     `tests/test_gemini_retry.py` verifies both behaviors with the Gemini
     client mocked out (no network needed).

7. **Confidence numbers are honestly caveated, not dressed up.** OCR and
   entity-extraction confidence are self-reported by Gemini in the prompt —
   they are **not calibrated probabilities**. This is stated here explicitly
   rather than presented as a real metric. A production version would
   cross-check against something with a real confidence signal (e.g. a
   traditional OCR engine's word-level confidences, or self-consistency
   across repeated calls).

8. **Idempotency keys for `/schedule` — the exact case they exist for.**
   This endpoint can take several seconds (two sequential Gemini calls) and
   is a real network operation a client can time out on and retry, or a
   user can double-click "Submit" on. Without protection, a retry means a
   second real Gemini round-trip, and since Gemini's output isn't
   byte-for-byte deterministic across identical calls, a slightly different
   resolved time close to another booking's buffer window could either
   double-book a near-duplicate slot or bounce as a confusing
   `slot_conflict` for what should be recognized as the same logical
   request. Stripe's idempotency-key pattern
   ([source](https://docs.stripe.com/api/idempotent_requests)) solves
   exactly this: a client sends an optional `Idempotency-Key` header; the
   server stores the first response under that key and replays it verbatim
   on any retry with the same key, instead of reprocessing. Implemented in
   `app/services/idempotency.py` + `idempotency_keys` table
   (`0005_add_idempotency_keys.py`). Also matches Stripe's behavior for a
   reused key with *different* parameters (a request fingerprint mismatch)
   — that returns a `422`, not a silently-wrong replayed answer. Verified
   live: an identical retried request returned in 0.003s instead of the
   original 4.2s, with no duplicate row created; a same-key-different-body
   request was correctly rejected. Deliberately scoped to only cache a
   completed pipeline run (`ok`/`needs_clarification`/`slot_conflict`) —
   a transient Gemini failure (502) is never cached, so retrying after a
   real infrastructure failure actually retries instead of replaying that
   failure forever. Known gap: keys never expire here (no cleanup job in a
   demo), where Stripe's own retention window is 24 hours.

9. **A real `dateparser` bug, worked around and documented.** `dateparser`
   1.4.3 fails to parse `"next Friday"` or `"this Friday"` as a single phrase
   (it returns `None`), even though it parses `"Friday"` alone and
   `"next week"` alone just fine — found while writing the unit tests, not in
   any changelog. `normalize.py` retries with the leading `next`/`this`/`coming`
   stripped and relies on `PREFER_DATES_FROM="future"` to still pick the
   correct upcoming weekday. This also happens to be the least-surprising
   resolution of "next Friday"'s inherent ambiguity (nearest Friday vs. one
   week out) since it always resolves to the closest future occurrence.

10. **A real Postgres 18 image-layout change, worked around and documented.**
   The official `postgres:18` Docker image restructured how it stores data on
   disk (major-version-specific subdirectories, to support `pg_ctlcluster`
   -style upgrades) and now expects the volume mounted at
   `/var/lib/postgresql`, not the pre-18 `/var/lib/postgresql/data`. Mounting
   at the old path makes the container start but fail its healthcheck with
   an explicit error in `docker logs`. Found by actually running
   `docker compose up` and reading the failure, not by reading changelogs
   first — `docker-compose.yml`'s volume mount reflects the fix.

11. **A self-audit of the pipeline found five more real bugs, verified with
   actual probes, not just reasoned about:**
   - `dateparser` accepted a fully-specified *past* date/time as-is (e.g.
     "2020-01-01 3pm", or "today" once that time of day had already passed)
     — `PREFER_DATES_FROM="future"` only disambiguates incomplete/relative
     phrases, it doesn't push a literal date forward. An appointment
     scheduler booking something in the past is always wrong, so
     `normalize.py` now explicitly rejects any resolved timestamp that
     isn't after "now."
   - A missing time phrase silently defaulted to midnight (`dateparser`'s
     own behavior for a date with no time attached), which would have
     booked a real midnight appointment instead of asking for
     clarification. Both `date_phrase` and `time_phrase` are now required
     to be non-blank before parsing is even attempted.
   - Gemini doesn't reliably follow prose instructions: asked to return an
     empty string for a missing date/time phrase, it was observed live
     returning the literal word `"null"` instead. `normalize.py` treats a
     small set of placeholder words (`null`, `none`, `n/a`, `unknown`, ...)
     as blank rather than trusting the model's compliance — the same
     "validate at the boundary" philosophy already used for the
     department enum, applied because it was actually needed, not
     hypothetically.
   - Confidence values from Gemini (`OCRSchema.confidence`,
     `entities_confidence`) had no range constraint, even though every
     downstream guardrail is a threshold comparison against them. Both are
     now `Field(ge=0.0, le=1.0)`, so an out-of-range value fails schema
     validation (surfaced as a clean 502) instead of silently corrupting a
     threshold check.
   - `Normalized.date`/`.time` were plain `str` fields with no format
     validation. POSTing a malformed value directly to `/appointments` or
     `/normalize` (each step is independently callable, per the
     assignment's own curl/Postman requirement) reached
     `date.fromisoformat()` deep in `scheduler.py`, raised a bare
     `ValueError`, and got mislabeled by the router as "ambiguous
     department" — a confusing, wrong guardrail for what was actually a
     malformed-date problem. Both fields now have Pydantic validators that
     turn this into a proper `422` at the API boundary instead.
   - The frontend echoed `raw_text` (whatever the user typed) back into
     the page via `innerHTML` using `JSON.stringify`, which does not
     HTML-escape `<`/`>`. Input like `Book dentist<img src=x
     onerror=alert(1)>` would have executed as markup when the trace
     rendered. All dynamic content in `static/index.html` is now passed
     through an explicit `escapeHtml()` before insertion.

12. **Known scope simplifications** (deliberate, for a 3-day assignment):
   - One resource per department (no multiple doctors/rooms/time-of-day
     capacity) — booking a slot occupies the whole department for that
     department+date+time.
   - Business hours and closed days are global, not per-department.
   - Department matching is a fixed, seeded list (`alembic/versions/0002_seed_departments.py`),
     not a self-service admin CRUD.
   - No auth — single-tenant demo, as implied by the spec.

## Project layout

```
app/
  main.py               FastAPI app + static frontend mount
  config.py              Settings (.env via pydantic-settings)
  db.py                   Async SQLAlchemy engine/session
  constants.py             Scheduling constants shared by app + migrations (cited sources)
  models.py                Department, Appointment, IdempotencyKey
  schemas.py               Pydantic request/response models (spec-exact JSON shapes)
  gemini_client.py         Async Gemini SDK wrapper (OCR + entity extraction, retry w/ backoff)
  guardrails.py             needs_clarification / slot_conflict response builders
  services/
    ocr.py                  text passthrough vs image OCR
    entities.py              entity extraction
    normalize.py             deterministic date/time resolution (pure function)
    scheduler.py              department lookup, conflict-checked persistence
    idempotency.py            Idempotency-Key lookup/store for /schedule
  routers/
    pipeline.py               /ocr /entities /normalize /appointments /schedule
    departments.py             /departments
alembic/                     5 migrations: schema, seed data, overlap constraint,
                              buffer, idempotency_keys table
static/index.html             minimal frontend
tests/                        unit tests: normalize, guardrails, Gemini retry policy,
                              idempotency fingerprinting - no DB/network required
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

Outside business hours (nobody is taking a 2am dentist appointment):

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist tomorrow at 2am"
# result.status == "needs_clarification", message mentions "business hours"
```

Closed day:

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist this Sunday at 11am"
# result.status == "needs_clarification", message mentions "closed"
```

Too little notice (needs at least 60 minutes) — replace with a time that's
genuinely under an hour from when you run this:

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist today at <a time <60 min from now>"
# result.status == "needs_clarification", message mentions "notice"
```

Beyond the booking horizon (more than 60 days out):

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist on 2028-01-01 at 3pm"
# result.status == "needs_clarification", message mentions "advance"
```

Double-booking the exact same slot:

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 3pm"
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 3pm"
# second call: result.status == "slot_conflict"
```

Booked inside another appointment's buffer (10 minutes after the 30-minute
block ends, so 10:35 conflicts with a 10:00 booking even though 10:00-10:30
itself is free):

```bash
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 10am"
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 10:35am"
# second call: result.status == "slot_conflict"
curl -X POST http://localhost:8000/api/v1/schedule -F "text=Book dentist next Friday at 10:40am"
# this one succeeds - exactly the 10-minute buffer past the first booking's end
```

Retrying the same request with an idempotency key (the second call replays
the first's result instantly instead of re-running the Gemini pipeline or
creating a duplicate booking):

```bash
curl -X POST http://localhost:8000/api/v1/schedule \
  -H "Idempotency-Key: demo-key-1" \
  -F "text=Book ENT next Wednesday at 9am"
curl -X POST http://localhost:8000/api/v1/schedule \
  -H "Idempotency-Key: demo-key-1" \
  -F "text=Book ENT next Wednesday at 9am"
# second call: identical response, returns in milliseconds, no new row created

curl -X POST http://localhost:8000/api/v1/schedule \
  -H "Idempotency-Key: demo-key-1" \
  -F "text=Book dermatology next Thursday at 2pm"
# same key, different request body: HTTP 422
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
| Date/time phrase unparsable, blank, or a placeholder word (`null`/`none`/...) | `{"status": "needs_clarification", ...}` |
| Resolved date/time is not in the future | `{"status": "needs_clarification", ...}` (see Design Decisions #11) |
| Less than 60 minutes' notice, or more than 60 days in advance | `{"status": "needs_clarification", ...}` (see Design Decisions #5) |
| Requested time is outside business hours, or its 30-minute block runs past closing | `{"status": "needs_clarification", ...}` (see Design Decisions #4) |
| Requested date falls on a closed weekday (Sunday) | `{"status": "needs_clarification", ...}` (see Design Decisions #4) |
| Requested time overlaps an existing booking, including its 10-minute buffer | `{"status": "slot_conflict", ...}` (extension, see Design Decisions #3) |
| Malformed `date`/`time` string posted directly to `/appointments` or `/normalize` | `422 Unprocessable Entity` (schema validation, see Design Decisions #11) |
| `Idempotency-Key` reused with a different request body | `422 Unprocessable Entity` (see Design Decisions #8) |
| Gemini API error/timeout | HTTP 502 with a plain error message |
| Oversized/non-image upload | HTTP 413 / 400 |

## Known limitations

- Self-reported LLM confidence is a heuristic (see Design Decisions #7).
- Idempotency keys never expire (see Design Decisions #8) — a production
  system would need a scheduled cleanup job.
- Fixed 30-minute appointment duration for every department (see Design
  Decisions #3) — a real system would need per-department or per-visit-type
  durations, which would mean storing duration per row instead of baking a
  single constant into the DB constraint.
- Single resource per department; no per-doctor/room scheduling.
- No auth/multi-tenancy — out of scope for this assignment.
