import json
import os
from pathlib import Path

import requests

try:
    from lloyds_digest.utils import load_env_file
except Exception:
    load_env_file = None

if load_env_file:
    load_env_file(Path(".env"))

api_key = os.environ.get("OPENROUTER_API_KEY")
if not api_key:
    raise SystemExit("Missing OPENROUTER_API_KEY in environment")

model = "arcee-ai/trinity-large-preview:free"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

first_payload = {
    "model": model,
    "messages": [
        {"role": "user", "content": "How many r's are in the word 'strawberry'?"}
    ],
    "reasoning": {"enabled": True},
}

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    data=json.dumps(first_payload),
    timeout=120,
)
response.raise_for_status()
first_data = response.json()
assistant_message = first_data["choices"][0]["message"]

messages = [
    {"role": "user", "content": "How many r's are in the word 'strawberry'?"},
    {
        "role": "assistant",
        "content": assistant_message.get("content"),
        "reasoning_details": assistant_message.get("reasoning_details"),
    },
    {"role": "user", "content": "Are you sure? Think carefully."},
]

second_payload = {
    "model": model,
    "messages": messages,
    "reasoning": {"enabled": True},
}

response2 = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    data=json.dumps(second_payload),
    timeout=120,
)
response2.raise_for_status()
second_data = response2.json()

print("first_response:")
print(json.dumps(first_data, indent=2))
print("second_response:")
print(json.dumps(second_data, indent=2))
