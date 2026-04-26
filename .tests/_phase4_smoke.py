import asyncio
import json
import httpx

from src.modules.inference.internal import (
    body_hasher, shortener_registry, prompts, page_scraper,
    link_unshortener, groq_client, gemini_client,
)
from src.modules.inference.domain.models.enums import ResolveStatus
from src.shared.exceptions import ServiceUnavailableException


# ── 1. body_hasher ──────────────────────────────────
h1 = body_hasher.hash_body("hello world")
h2 = body_hasher.hash_body("hello world")
h3 = body_hasher.hash_body("hello world!")
assert h1 == h2 and len(h1) == 64 and h1.islower() and h1 != h3
print("body_hasher: deterministic, lowercase hex, 64 chars OK")


# ── 2. shortener_registry ───────────────────────────
assert shortener_registry.is_shortener("bit.ly")
assert shortener_registry.is_shortener("BIT.LY")
assert shortener_registry.is_shortener("www.tinyurl.com")
assert not shortener_registry.is_shortener("example.com")
assert "bit.ly" in shortener_registry.KNOWN_SHORTENERS
print("shortener_registry: case-insensitive, www-tolerant, registry intact OK")


# ── 3. prompts ──────────────────────────────────────
s1 = prompts.format_stage_1("evil@x.com", "Subj", "BODY")
assert "Sender: evil@x.com" in s1 and "Subject: Subj" in s1 and "BODY" in s1
assert "<email_body>" in s1 and "</email_body>" in s1
assert '"classification"' in s1

s3 = prompts.format_stage_3([
    {"resolved_url": "https://a.test", "page_title": "A", "has_login_form": True,
     "external_domains": ["cdn.x"], "content": "hi"},
    {"resolved_url": "https://b.test", "page_title": "B", "has_payment_form": True,
     "content": "buy"},
])
assert "PAGE_1:" in s3 and "PAGE_2:" in s3
assert "<pages>" in s3 and "</pages>" in s3
assert "HAS_LOGIN_FORM: true" in s3 and "HAS_PAYMENT_FORM: true" in s3
print("prompts: Stage-1 and Stage-3 templates format correctly OK")


# ── 4. page_scraper.parse_html (no network) ─────────
html = """<html><head>
  <title>Sign in to PayPaI</title>
  <meta name="description" content="Login to your account">
  <link rel="icon" href="https://cdn.evil.xyz/favicon.ico">
  <script src="https://cdn.tracker.io/x.js"></script>
</head><body>
  <form>
    <input name="email" type="email">
    <input name="password" type="password">
    <input name="cardNumber" autocomplete="cc-number">
  </form>
  <p>Welcome back. Please sign in.</p>
</body></html>"""
page = page_scraper.parse_html(html, "https://paypal-secure-login.xyz/login")
assert page.page_title == "Sign in to PayPaI"
assert page.meta_description == "Login to your account"
assert page.has_login_form is True
assert page.has_payment_form is True
assert "cdn.evil.xyz" in page.external_domains
assert "cdn.tracker.io" in page.external_domains
assert page.favicon_matches_domain is False
assert "Welcome back" in page.body_text
print("page_scraper: title, meta, login/payment, externals, favicon mismatch OK")


# ── 5. link_unshortener with mocked httpx ──────────
async def test_unshortener():
    def handler(req):
        if req.url.host == "bit.ly":
            return httpx.Response(301, headers={"Location": "https://example.com/final"})
        return httpx.Response(200, text="ok")
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    try:
        result = await link_unshortener.resolve_url(
            "https://bit.ly/abc",
            httpx_client=mock,
            timeout_1=2, use_playwright=False,
        )
    finally:
        await mock.aclose()
    assert result.status == ResolveStatus.SUCCESS, result
    assert result.resolved_url == "https://example.com/final"
    assert result.hops == 1
    assert result.attempt == 1
    assert "bit.ly" in result.intermediate_domains
    print("link_unshortener (success): resolved + hop counted OK")

    def fail_handler(req):
        raise httpx.ConnectError("simulated DNS failure")
    fail_client = httpx.AsyncClient(transport=httpx.MockTransport(fail_handler))
    try:
        result = await link_unshortener.resolve_url(
            "https://bit.ly/dead",
            httpx_client=fail_client,
            timeout_1=2, timeout_2=2, use_playwright=False,
        )
    finally:
        await fail_client.aclose()
    assert result.status == ResolveStatus.BLOCKED, result.status
    assert result.resolved_url is None
    print("link_unshortener (failure): BLOCKED after escalation OK")

asyncio.run(test_unshortener())


# ── 6. groq_client with mocked httpx ────────────────
async def test_groq():
    captured = {}
    def handler(req):
        captured["url"] = str(req.url)
        captured["payload"] = json.loads(req.content)
        captured["auth"] = req.headers.get("Authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"classification": "phishing", "confidence": 0.9})}}]
        })
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await groq_client.chat_json(
            messages=[{"role": "user", "content": "Hello"}],
            model="llama-3.1-8b-instant",
            api_key="test-key",
            client=mock,
        )
    finally:
        await mock.aclose()
    assert result == {"classification": "phishing", "confidence": 0.9}
    assert captured["url"] == groq_client.GROQ_ENDPOINT
    assert captured["payload"]["model"] == "llama-3.1-8b-instant"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["messages"][0]["role"] == "user"
    assert captured["auth"] == "Bearer test-key"
    print("groq_client (success): correct request shape, parsed JSON returned OK")

    err_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="kaboom")))
    raised = False
    try:
        await groq_client.chat_json([{"role": "user", "content": "x"}], api_key="k", client=err_client)
    except ServiceUnavailableException as e:
        assert e.error_detail.code == "LLM_UNAVAILABLE"
        raised = True
    finally:
        await err_client.aclose()
    assert raised
    print("groq_client (failure): raises ServiceUnavailableException(LLM_UNAVAILABLE) OK")

asyncio.run(test_groq())


# ── 7. gemini_client with mocked httpx ──────────────
async def test_gemini():
    captured = {}
    def handler(req):
        captured["url"] = str(req.url)
        captured["payload"] = json.loads(req.content)
        body = json.dumps([{"page_index": 1, "risk_level": "high"}])
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": body}]}}]
        })
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await gemini_client.generate_json(
            prompt="page block here",
            model="gemini-1.5-flash",
            api_key="test-key",
            client=mock,
        )
    finally:
        await mock.aclose()
    assert result == [{"page_index": 1, "risk_level": "high"}]
    assert "gemini-1.5-flash:generateContent" in captured["url"]
    assert "key=test-key" in captured["url"]
    assert captured["payload"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["payload"]["contents"][0]["parts"][0]["text"] == "page block here"
    print("gemini_client (success): correct URL, JSON-mode flag, parsed body OK")

    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"unexpected": "shape"})))
    raised = False
    try:
        await gemini_client.generate_json("p", api_key="k", client=bad)
    except ServiceUnavailableException as e:
        assert e.error_detail.code == "LLM_UNAVAILABLE"
        raised = True
    finally:
        await bad.aclose()
    assert raised
    print("gemini_client (failure): raises ServiceUnavailableException(LLM_UNAVAILABLE) OK")

asyncio.run(test_gemini())


# ── 8. playwright_scraper module imports ────────────
from src.modules.inference.internal import playwright_scraper as pws
assert hasattr(pws, "fetch_with_browser")
assert hasattr(pws, "resolve_with_browser")
assert hasattr(pws, "shutdown_browser")
print("playwright_scraper: importable; chromium binary not exercised here OK")
print()
print("All Phase-4 helper smoke tests passed.")
