"""Verifies _call_with_retry's actual policy: retry transient errors
(429/503) with backoff, fail immediately on everything else. Mocks the
Gemini client entirely - no network access, no API key needed.
"""

from unittest.mock import AsyncMock, patch

import pytest
from google.genai import errors as genai_errors

from app.gemini_client import GeminiServiceError, _call_with_retry


def _api_error(code: int) -> genai_errors.APIError:
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return cls(code=code, response_json={"error": {"message": "boom", "status": "X"}})


async def test_retries_transient_503_and_eventually_succeeds():
    mock_generate = AsyncMock(side_effect=[_api_error(503), _api_error(503), "ok-response"])
    with patch("app.gemini_client._client.aio.models.generate_content", mock_generate), patch(
        "app.gemini_client.asyncio.sleep", AsyncMock()
    ):
        result = await _call_with_retry(model="m", contents="c")
    assert result == "ok-response"
    assert mock_generate.call_count == 3


async def test_gives_up_after_max_attempts_on_persistent_503():
    mock_generate = AsyncMock(side_effect=_api_error(503))
    with patch("app.gemini_client._client.aio.models.generate_content", mock_generate), patch(
        "app.gemini_client.asyncio.sleep", AsyncMock()
    ):
        with pytest.raises(GeminiServiceError):
            await _call_with_retry(model="m", contents="c")
    from app.gemini_client import _MAX_ATTEMPTS

    assert mock_generate.call_count == _MAX_ATTEMPTS


async def test_does_not_retry_permanent_400_error():
    # A malformed request will fail identically every time - retrying just
    # burns quota and delays an error the caller could've had immediately.
    mock_generate = AsyncMock(side_effect=_api_error(400))
    with patch("app.gemini_client._client.aio.models.generate_content", mock_generate), patch(
        "app.gemini_client.asyncio.sleep", AsyncMock()
    ) as mock_sleep:
        with pytest.raises(GeminiServiceError):
            await _call_with_retry(model="m", contents="c")
    assert mock_generate.call_count == 1
    mock_sleep.assert_not_called()
