from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import sys


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, Path('scripts') / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_digest_uses_selected_model_and_returned_tier(monkeypatch):
    module = load_script('render_digest_llm_compare')
    monkeypatch.setenv('OPENAI_API_KEY', 'key')
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-6-luna')
    calls = []
    def respond(prompt, **kwargs):
        calls.append(kwargs)
        return {'service_tier': 'default', 'data': {'usage': {'prompt_tokens': 100}, 'choices': [{'message': {'content': json.dumps({'executive_summary': 'Insurance news', 'themes': [], 'items': [{'id': '1'}]})}}]}}
    monkeypatch.setattr(module, 'post_openai_chat_completion', respond)
    result = module.generate_with_openai({'schema': {}, 'items': []}, SimpleNamespace(llm_prompts={}), '2026-10-08')
    assert calls[0]['model'] == 'gpt-6-luna'
    assert result['_service_tier'] == 'default'
    assert result['items']


def test_summary_preserves_billing_metadata(monkeypatch):
    import importlib
    module = importlib.import_module("lloyds_digest.ai.summarise")
    monkeypatch.setattr(module.OpenAIClient, 'generate', lambda self, prompt: {'response': '{"bullets": ["A", "B", "C"]}', 'service_tier': 'default', 'raw': {'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 25, 'cache_write_tokens': 10}}}})
    result = module.summarise('source text', 'gpt-6-luna')
    assert result['service_tier'] == 'default'
    assert result['tokens_cached_prompt'] == 25
    assert result['tokens_cache_write'] == 10


def test_cached_pipeline_stage_does_not_record_new_spend(monkeypatch):
    import lloyds_digest.pipeline as module
    costs = []
    monkeypatch.setattr(module, '_record_llm_cost', lambda **kwargs: costs.append(kwargs))
    postgres = SimpleNamespace(insert_llm_usage=lambda **kwargs: None)
    result = module._run_llm_stage('summarise', 'gpt-6-luna', 'v2', lambda: {'cached': True, 'parsed': {'bullets': ['Fact']}, 'tokens_prompt': 100, 'tokens_completion': 20}, postgres, 'run', 'article', [])
    assert result['cached']
    assert costs == []
