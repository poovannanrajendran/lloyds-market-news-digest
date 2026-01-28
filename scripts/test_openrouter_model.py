import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

MODEL = "meta-llama/llama-3.3-70b-instruct:free"
TIMEOUT = 360
MAX_TOKENS = 2000

try:
    from lloyds_digest.utils import load_env_file
except Exception:
    load_env_file = None

if load_env_file:
    load_env_file(Path(".env"))

API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    print("Missing OPENROUTER_API_KEY")
    sys.exit(1)

prompt = (
    "Return JSON only. No markdown, no prose, no code fences. "
    "You MUST end the response with a valid JSON object that closes all brackets (end with ']}'). "
    "Schema: {\"executive_summary\": \"string\", \"themes\": [\"string\"], "
    "\"items\": [{\"id\": \"string\", \"why\": \"string\", \"bullets\": [\"string\"]}]}\n\n"
    "Items: [{\"id\": \"a1\", \"title\": \"Test item\", \"url\": \"https://example.com\", "
    "\"source\": \"example.com\", \"published_at\": \"2026-01-28T00:00:00Z\", "
    "\"excerpt\": \"A short test item for JSON output.\"}]"
)

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

body = {
    "model": MODEL,
    "messages": [
        {
            "role": "system",
            "content": "Return JSON only. No markdown, no prose, no code fences. "
            "You MUST end with a valid JSON object (close all brackets).",
        },
        {"role": "user", "content": prompt},
    ],
    "temperature": 0.2,
    "max_tokens": MAX_TOKENS,
}

started = datetime.now(timezone.utc)
print(f"start={started.isoformat()} model={MODEL} timeout={TIMEOUT} max_tokens={MAX_TOKENS}")

with httpx.Client(timeout=TIMEOUT) as client:
    resp = client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)
    print(f"status={resp.status_code}")
    if resp.status_code >= 400:
        print(resp.text)
        sys.exit(1)
    data = resp.json()

content = data["choices"][0]["message"]["content"]
print("raw:")
print(content)

try:
    parsed = json.loads(content)
    print("parsed_ok=true")
    print(parsed)
except Exception as exc:
    print("parsed_ok=false", exc)
    sys.exit(2)
