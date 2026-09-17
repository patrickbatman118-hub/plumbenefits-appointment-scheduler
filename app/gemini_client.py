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
"""

from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, create_model

from app.config import get_settings

settings = get_settings()
_client = genai.Client(api_key=settings.gemini_api_key)


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


def ocr_image(image_bytes: bytes, mime_type: str) -> OCRSchema:
    prompt = (
        "Transcribe the exact text visible in this image of a handwritten or typed "
        "appointment note or email. Do not correct spelling, do not add words that "
        "are not visible, and do not translate. Also give your own confidence "
        "(0 to 1) in the transcription's accuracy, based on legibility and clarity."
    )
    try:
        response = _client.models.generate_content(
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
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain-specific error
        raise GeminiServiceError(f"OCR call failed: {exc}") from exc
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


def extract_entities(raw_text: str, department_choices: list[str]):
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
    try:
        response = _client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain-specific error
        raise GeminiServiceError(f"Entity extraction call failed: {exc}") from exc
    return _require_parsed(response)
