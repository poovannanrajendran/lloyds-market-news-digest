from __future__ import annotations

from dataclasses import dataclass

import pytest

import lloyds_digest.ai.base as ai_base


@dataclass
class _DummyResponse:
    status_code: int
    text: str
    payload: dict | None = None

    def json(self) -> dict:
        return self.payload or {}

    @property
    def request(self):  # pragma: no cover - only needed for raised exceptions
        return object()

    def raise_for_status(self) -> None:
        raise RuntimeError(self.text)


class _DummyClient:
    calls: list[dict] = []

    def __init__(self, timeout: float):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, headers: dict, json: dict):
        self.calls.append({"url": url, "headers": headers, "json": dict(json)})
        if len(self.calls) == 1:
            return _DummyResponse(429, "resource_unavailable")
        return _DummyResponse(
            200,
            "",
            payload={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            },
        )


def test_post_openai_chat_completion_falls_back_to_standard(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = _DummyClient
    dummy.calls = []
    monkeypatch.setattr(ai_base.httpx, "Client", dummy)

    result = ai_base.post_openai_chat_completion(
        "hello",
        model="gpt-5-mini",
        api_key="key",
        service_tier="flex",
        fallback_tier="standard",
        timeout=1.0,
        system_prompt="Return JSON only, no markdown.",
    )

    assert result["service_tier"] == "default"
    assert len(dummy.calls) == 2
    assert dummy.calls[0]["json"]["service_tier"] == "flex"
    assert dummy.calls[1]["json"]["service_tier"] == "default"

@pytest.mark.parametrize('client_path', ['shared', 'pipeline'])
def test_luna_payload_and_fallback(monkeypatch, client_path):
    dummy = _DummyClient
    dummy.calls = []
    monkeypatch.setattr(ai_base.httpx, 'Client', dummy)
    monkeypatch.setenv('OPENAI_API_KEY', 'key')
    monkeypatch.setenv('OPENAI_REASONING_EFFORT', 'none')
    monkeypatch.setenv('OPENAI_MAX_COMPLETION_TOKENS', '8192')
    if client_path == 'shared':
        result = ai_base.post_openai_chat_completion('hello', model='gpt-6-luna', api_key='key', service_tier='flex', fallback_tier='standard', timeout=1, system_prompt='JSON', temperature=.2)
    else:
        result = ai_base.OpenAIClient(model='gpt-6-luna', service_tier='flex').generate('hello')
    assert result['service_tier'] == 'default'
    for call in dummy.calls:
        payload = call['json']
        assert 'temperature' not in payload
        assert payload['reasoning_effort'] == 'none'
        assert payload['max_completion_tokens'] == 8192
    assert dummy.calls[-1]['json']['service_tier'] == 'default'


def test_reported_service_tier_takes_precedence(monkeypatch):
    class ActualTierClient(_DummyClient):
        def post(self, url, headers, json):
            return _DummyResponse(200, '', {'choices': [{'message': {'content': '{}'}}], 'service_tier': 'default'})
    monkeypatch.setattr(ai_base.httpx, 'Client', ActualTierClient)
    result = ai_base.post_openai_chat_completion('hello', model='gpt-6-luna', api_key='key', service_tier='flex', fallback_tier='default', timeout=1, system_prompt='JSON')
    assert result['service_tier'] == 'default'

@pytest.mark.parametrize('content,reason', [('', 'stop'), ('{}', 'length'), ('[]', 'stop')])
def test_invalid_luna_output_is_rejected(content, reason):
    with pytest.raises(ValueError):
        ai_base.validate_openai_response({'choices': [{'finish_reason': reason, 'message': {'content': content}}]}, json_only=True)
