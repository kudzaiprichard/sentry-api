KNOWN_SHORTENERS: frozenset[str] = frozenset({
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "ow.ly",
    "short.io",
    "rb.gy",
    "is.gd",
    "buff.ly",
    "cutt.ly",
    "adf.ly",
})


def _normalise(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def is_shortener(domain: str) -> bool:
    return _normalise(domain) in KNOWN_SHORTENERS
