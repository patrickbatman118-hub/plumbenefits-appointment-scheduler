"""Stripe-style idempotency keys for POST /api/v1/schedule.

Lookup/store for the cache; the policy of what gets cached (only a
completed pipeline run, never a transient Gemini failure) lives in
routers/pipeline.py's schedule_endpoint. Full rationale in README "Design
Decisions" #8. Known limitation: keys never expire (no cleanup job here;
Stripe's own retention window is 24h).
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
