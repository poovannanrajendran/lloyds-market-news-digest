from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


UTM_PREFIX = "utm_"


def canonicalise_url(url: str) -> str:
    parts = urlsplit(url)
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(UTM_PREFIX)
    ]
    query = urlencode(query_pairs, doseq=True)
    normalized = parts._replace(query=query, fragment="")
    return urlunsplit(normalized)


def candidate_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()
