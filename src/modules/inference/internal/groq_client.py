import asyncio
import json
import logging
from typing import Optional, Sequence

import httpx

from src.configs import inference
from src.shared.exceptions import ServiceUnavailableException
from src.shared.responses.api_response import ErrorDetail


logger = logging.getLogger(__name__)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def _llm_unavailable(reason: str) -> ServiceUnavailableException:
    return ServiceUnavailableException(
        message="The classification service is temporarily unavailable",
        error_detail=ErrorDetail(
            title="LLM Unavailable",
            code="LLM_UNAVAILABLE",
            status=503,
            details=[reason],
        ),
    )


async def chat_json(
    messages: Sequence[dict],
    *,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    api_key: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """
    POST to Groq chat-completions in JSON-object mode and return the parsed
    JSON body of the assistant message. Retries once on 429 with a short
    backoff. Raises ServiceUnavailableException(LLM_UNAVAILABLE) on persistent
    failure or on a non-2xx response after retry.
    """
    model = model or inference.groq.model
    timeout = timeout or inference.groq.timeout_seconds
    api_key = api_key or inference.groq.api_key

    payload = {
        "model": model,
        "messages": list(messages),
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        response: Optional[httpx.Response] = None
        for attempt in (1, 2):
            try:
                response = await client.post(GROQ_ENDPOINT, json=payload, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise _llm_unavailable(f"Groq request failed: {e}")
                await asyncio.sleep(0.5)
                continue

            if response.status_code == 429 and attempt == 1:
                logger.warning("Groq rate-limited; retrying once")
                await asyncio.sleep(1.0)
                continue
            break

        if response is None or response.status_code >= 400:
            status = response.status_code if response is not None else "no response"
            body = response.text[:200] if response is not None else ""
            raise _llm_unavailable(f"Groq returned {status}: {body}")

        data = response.json()
    finally:
        if own:
            await client.aclose()

    try:
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise _llm_unavailable(f"Groq response was malformed: {e}")
