"""Stripe-style idempotency keys for POST /api/v1/schedule.

An AI-pipeline endpoint is exactly the case idempotency keys exist for
(https://stripe.com/blog/idempotency,
https://docs.stripe.com/api/idempotent_requests): each request can take
multiple seconds (OCR + entity extraction, both real network calls to
Gemini) and is something a client can legitimately time out on and retry,
or a user can double-click "Submit" on. Without a key, retrying an
already-succeeded booking risks a second real Gemini round-trip and - since
Gemini's output isn't byte-for-byte deterministic across calls - a
newly-resolved time close enough to another booking's buffer window to
either silently create a second, slightly-different appointment or bounce
as a confusing slot_conflict for what should be recognized as the exact
same logical request.

Scope: only a completed pipeline run (status ok / needs_clarification /
slot_conflict - any determinate business outcome) is cached and replayed.
A transient infrastructure failure (a 502 from Gemini) is NOT cached, so
retrying after a transient failure genuinely retries instead of replaying
the same failure forever - see app/routers/pipeline.py's schedule_endpoint
for where that boundary is drawn.

Known limitation: keys never expire here (a demo has no cleanup job).
Stripe's own retention window is 24 hours; a production version would need
a scheduled cleanup, not indefinite storage. Also unlike Stripe, a key
collision with a different request returns a plain 422 rather than a
dedicated error type - adequate for this scope, not a full reimplementation
of Stripe's API.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyKey


def fingerprint(text: str | None, image_bytes: bytes | None) -> str:
    """Detects a key reused with different request parameters (Stripe does
    the same param comparison) - not for security, just to catch a client
    bug rather than silently replaying the wrong cached answer."""
    hasher = hashlib.sha256()
    if image_bytes is not None:
        hasher.update(b"image:")
        hasher.update(image_bytes)
    else:
        hasher.update(b"text:")
        hasher.update((text or "").encode())
    return hasher.hexdigest()


async def get(db: AsyncSession, key: str) -> IdempotencyKey | None:
    result = await db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key))
    return result.scalar_one_or_none()


async def store(db: AsyncSession, key: str, request_fingerprint: str, response_body: dict) -> None:
    db.add(
        IdempotencyKey(
            key=key,
            request_fingerprint=request_fingerprint,
            response_status=200,
            response_body=response_body,
        )
    )
    await db.commit()
