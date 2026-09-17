"""Thin wrapper over the google-genai SDK.

Two calls only, both using Gemini's structured-output mode (response_schema)
so the model is contractually forced to return schema-valid JSON instead of
free text we'd have to parse and hope for the best:

1. ocr_image        - image bytes -> {raw_text, confidence}
2. extract_entities - raw text    -> {date_phrase, time_phrase, department, entities_confidence}

For extract_entities, `department` is typed as a Literal built dynamically
from the department names currently in the database (+ "unclear"). That
makes it schema-impossible for the model to return a department that
doesn't exist in our system - see services/entities.py and the README's
"Design Decisions" section for the full rationale.

Both calls are async and use `client.aio` (not the default `client`), and
both retry transient errors with backoff - see the comments below on
_call_with_retry for why both of those matter, not just how.
"""

import asyncio
import random
from typing import Literal

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field, create_model

from app.config import get_settings

settings = get_settings()
_client = genai.Client(api_key=settings.gemini_api_key)

# Google's own guidance for 429 (RESOURCE_EXHAUSTED) and 503 (UNAVAILABLE) is
# "wait and retry with exponential backoff" - these are transient (the
# service is temporarily overloaded), unlike e.g. a 400 (bad request) or
# 401/403 (auth), which will fail identically on every retry and shouldn't
# be retried at all.
# https://ai.google.dev/gemini-api/docs/troubleshooting
_RETRYABLE_STATUS_CODES = {429, 503}
_MAX_ATTEMPTS = 4
_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 15.0


class GeminiServiceError(Exception):
    """Raised when the Gemini API call fails or returns a response that
    doesn't conform to the requested schema."""


class OCRSchema(BaseModel):
    raw_text: str
    # Asking for "a confidence between 0 and 1" in the prompt is only a
    # request, not a guarantee - the schema enforces the range so an
    # out-of-bounds value fails validation (response.parsed is then None,
    # which _require_parsed turns into a clean 502) instead of silently
    # flowing into a threshold comparison downstream.
    confidence: float = Field(ge=0.0, le=1.0)


def _require_parsed(response):
    parsed = getattr(response, "parsed", None)
    if parsed is None:
        raise GeminiServiceError("Gemini returned a response that did not match the requested schema")
    return parsed


async def _call_with_retry(**generate_content_kwargs):
    """Calls the async Gemini client with exponential backoff + jitter on
    transient errors only. Deliberately not blind `except Exception: retry`
    - retrying a permanent error (bad API key, malformed request) just
    delays the same failure and burns quota for nothing.

    Uses `client.aio.models.generate_content` (a real coroutine), not
    `client.models.generate_content` (a blocking synchronous call). The
    earlier version of this file called the sync client directly from an
    `async def` FastAPI route - that blocks the entire single-process event
    loop for the full round-trip of every Gemini call (often several
    seconds), meaning the server couldn't handle *any* other request, not
    even an unrelated GET, while one Gemini call was in flight. Confirmed by
    inspecting the SDK directly: `inspect.iscoroutinefunction` is True for
    `client.aio.models.generate_content` and False for
    `client.models.generate_content`.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await _client.aio.models.generate_content(**generate_content_kwargs)
        except genai_errors.APIError as exc:
            last_exc = exc
            is_last_attempt = attempt == _MAX_ATTEMPTS - 1
            if exc.code not in _RETRYABLE_STATUS_CODES or is_last_attempt:
                raise GeminiServiceError(f"Gemini call failed: {exc}") from exc
            delay = min(_BASE_DELAY_SECONDS * (2**attempt), _MAX_DELAY_SECONDS) + random.uniform(0, 1)
            await asyncio.sleep(delay)
        except Exception as exc:  # noqa: BLE001 - re-raised as a domain-specific error
            raise GeminiServiceError(f"Gemini call failed: {exc}") from exc
    raise GeminiServiceError(f"Gemini call failed after {_MAX_ATTEMPTS} attempts: {last_exc}")


async def ocr_image(image_bytes: bytes, mime_type: str) -> OCRSchema:
    prompt = (
        "Transcribe the exact text visible in this image of a handwritten or typed "
        "appointment note or email. Do not correct spelling, do not add words that "
        "are not visible, and do not translate. Also give your own confidence "
        "(0 to 1) in the transcription's accuracy, based on legibility and clarity."
    )
    response = await _call_with_retry(
        model=settings.gemini_model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=OCRSchema,
        ),
    )
    return _require_parsed(response)


def build_entities_schema(department_choices: list[str]) -> type[BaseModel]:
    department_literal = Literal[tuple(department_choices + ["unclear"])]  # type: ignore[valid-type]
    return create_model(
        "EntitiesSchema",
        date_phrase=(str, ...),
        time_phrase=(str, ...),
        department=(department_literal, ...),
        entities_confidence=(float, Field(ge=0.0, le=1.0)),
    )


async def extract_entities(raw_text: str, department_choices: list[str]):
    schema = build_entities_schema(department_choices)
    prompt = (
        "You are extracting scheduling details from an appointment request.\n"
        "Extract:\n"
        "- date_phrase: the exact phrase referring to a date (e.g. 'next Friday'). "
        "If the request does not mention any date, return an empty string \"\" - "
        "never a placeholder word like 'null', 'none', or 'unknown'.\n"
        "- time_phrase: the exact phrase referring to a time (e.g. '3pm'). "
        "If the request does not mention any time, return an empty string \"\" - "
        "never a placeholder word like 'null', 'none', or 'unknown'.\n"
        "- department: MUST be exactly one value from the allowed list below. "
        "If nothing in the request clearly matches an allowed department, "
        "return 'unclear'. Never invent a department that is not in the list.\n"
        "- entities_confidence: your confidence (0 to 1) in this extraction\n\n"
        f"Allowed departments: {department_choices}\n\n"
        f"Request: \"{raw_text}\""
    )
    response = await _call_with_retry(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    return _require_parsed(response)
