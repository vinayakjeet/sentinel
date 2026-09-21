import hashlib
import re

_WS = re.compile(r"\s+")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_name(name: str) -> str:
    return _WS.sub(" ", name.strip().lower())
