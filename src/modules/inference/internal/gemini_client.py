import asyncio
import json
import logging
from typing import Optional

import httpx

from src.configs import inference
from src.shared.exceptions import ServiceUnavailableException
from src.shared.responses.api_response import ErrorDetail


logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _llm_unavailable(reason: str) -> ServiceUnavailableException:
    return ServiceUnavailableException(
        message="The page-analysis service is temporarily unavailable",
        error_detail=ErrorDetail(
            title="LLM Unavailable",
            code="LLM_UNAVAILABLE",
            status=503,
            details=[reason],
        ),
    )


def _build_payload(prompt: str) -> dict:
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }


async def generate_json(
    prompt: str,
    *,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    api_key: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict | list:
    """
    POST a single prompt to Gemini in JSON-mode and return the parsed JSON
    body of the response. Retries once on 429 with backoff. Raises
    ServiceUnavailableException(LLM_UNAVAILABLE) on persistent failure or
    a malformed body.
    """
    model = model or inference.gemini.model
    timeout = timeout or inference.gemini.timeout_seconds
    api_key = api_key or inference.gemini.api_key

    url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={api_key}"
    payload = _build_payload(prompt)
    headers = {"Content-Type": "application/json"}

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        response: Optional[httpx.Response] = None
        for attempt in (1, 2):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise _llm_unavailable(f"Gemini request failed: {e}")
                await asyncio.sleep(0.5)
                continue

            if response.status_code == 429 and attempt == 1:
                logger.warning("Gemini rate-limited; retrying once")
                await asyncio.sleep(1.0)
                continue
            break

        if response is None or response.status_code >= 400:
            status = response.status_code if response is not None else "no response"
            body = response.text[:200] if response is not None else ""
            raise _llm_unavailable(f"Gemini returned {status}: {body}")

        data = response.json()
    finally:
        if own:
            await client.aclose()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise _llm_unavailable(f"Gemini response was malformed: {e}")
