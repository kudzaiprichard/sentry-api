import hashlib


def hash_body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
