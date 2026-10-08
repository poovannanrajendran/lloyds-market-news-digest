import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("balance_checker", ROOT / "scripts/check_openai_balance.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def configuration():
    return {
        "OPENAI_API_ADMIN_KEY": "test-only",
        "OPENAI_BALANCE_BASELINE_USD": "9.98",
        "OPENAI_COSTS_BASELINE_USD": "0.342562925",
        "OPENAI_COSTS_START_TIME": "1790812800",
    }


@pytest.mark.parametrize("credit,alerts", [("1.01", 0), ("1.00", 1), ("0.99", 1), ("-0.01", 1)])
def test_inclusive_threshold_and_no_double_subtraction(tmp_path, credit, alerts):
    sent = []
    cost = Decimal("0.342562925") + Decimal("9.98") - Decimal(credit)
    checker.check(configuration(), tmp_path / "state.json", fetch=lambda *args: cost,
                  send=lambda *args: sent.append(args) or True)
    assert len(sent) == alerts
    assert Decimal(json.loads((tmp_path / "state.json").read_text())["estimated_balance_usd"]) == Decimal(credit)


def test_same_day_dedup_and_topup_resets_baseline(tmp_path):
    sent = []
    path = tmp_path / "state.json"
    env = configuration()
    fetch = lambda *args: Decimal("9.322562925")
    send = lambda *args: sent.append(args) or True
    for _ in range(2):
        checker.check(env, path, fetch=fetch, send=send)
    assert len(sent) == 1
    env["OPENAI_BALANCE_BASELINE_USD"] = "10.00"
    env["OPENAI_COSTS_BASELINE_USD"] = "9.322562925"
    checker.check(env, path, fetch=fetch, send=send)
    assert json.loads(path.read_text())["estimated_balance_usd"] == "10.000000000"
    assert "low_alert_date" not in json.loads(path.read_text())


def test_failed_delivery_retries(tmp_path):
    calls = []
    for _ in range(2):
        assert checker.check(configuration(), tmp_path / "state.json",
                             fetch=lambda *args: Decimal("10"),
                             send=lambda *args: calls.append(args) or False) == 1
    assert len(calls) == 2
    assert "low_alert_date" not in json.loads((tmp_path / "state.json").read_text())


def test_api_error_is_redacted_and_warned_once(tmp_path, capsys):
    sent = []
    def fetch(*args):
        raise urllib.error.HTTPError("https://example.invalid/secret", 403, "secret-key", {}, None)
    for _ in range(2):
        assert checker.check(configuration(), tmp_path / "state.json", fetch=fetch,
                             send=lambda *args: sent.append(args) or True) == 1
    assert len(sent) == 1
    assert "HTTP 403" in sent[0][0]
    assert "secret" not in str(sent) + capsys.readouterr().out


def test_missing_configuration_warns_instead_of_assuming_balance(tmp_path):
    sent = []
    assert checker.check({}, tmp_path / "state.json", send=lambda *args: sent.append(args) or True) == 1
    assert "unavailable" in sent[0][0]


def test_dry_run_has_no_delivery_or_state_changes(tmp_path):
    sent = []
    path = tmp_path / "state.json"
    checker.check(configuration(), path, dry_run=True, fetch=lambda *args: Decimal("10"),
                  send=lambda *args: sent.append(args) or True)
    assert not sent and not path.exists()


def test_costs_regression_is_not_assumed_to_be_a_topup(tmp_path):
    sent = []
    assert checker.check(configuration(), tmp_path / "state.json", fetch=lambda *args: Decimal("0"),
                         send=lambda *args: sent.append(args) or True) == 1
    assert "unavailable" in sent[0][0]


def test_low_balance_alert_repeats_on_next_london_day(tmp_path, monkeypatch):
    sent = []
    now = 1791489600
    monkeypatch.setattr(checker.time, "time", lambda: now)
    path = tmp_path / "state.json"
    for _ in range(2):
        checker.check(configuration(), path, fetch=lambda *args: Decimal("10"),
                      send=lambda *args: sent.append(args) or True)
        now += 86400
    assert len(sent) == 2


def test_corrupt_state_warns_and_recovers(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("broken json")
    sent = []
    assert checker.check(configuration(), path, fetch=lambda *args: Decimal("1"),
                         send=lambda *args: sent.append(args) or True) == 1
    assert "unavailable" in sent[0][0]
    assert checker.check(configuration(), path, fetch=lambda *args: Decimal("1"),
                         send=lambda *args: sent.append(args) or True) == 0


def test_missing_webhooks_is_a_delivery_failure():
    env = dict(os.environ, ALERT_WEBHOOK_SLACK="", ALERT_WEBHOOK_DISCORD="",
               ALERT_REQUIRE_DELIVERY="1")
    result = subprocess.run(["bash", str(ROOT / "scripts/notify_webhooks.sh"), "test"],
                            env=env, capture_output=True)
    assert result.returncode == 1


def test_pagination_all_projects_and_currencies(monkeypatch):
    requests = []
    responses = [
        {"data": [{"results": [{"amount": {"value": ".10", "currency": "usd"}},
                                  {"amount": {"value": ".20", "currency": "usd"}}]}],
         "has_more": True, "next_page": "next"},
        {"data": [{"results": [{"amount": {"value": ".30", "currency": "usd"}}]}],
         "has_more": False},
    ]
    from io import StringIO
    def open_request(req, **kwargs):
        requests.append(req.full_url)
        return StringIO(json.dumps(responses.pop(0)))
    monkeypatch.setattr(checker.urllib.request, "urlopen", open_request)
    assert checker.fetch_costs("dummy", 1, 2) == Decimal(".60")
    assert "page=next" in requests[1]
    assert all("project_ids" not in req and "api_key_ids" not in req for req in requests)


@pytest.mark.parametrize("code", [0, 7])
def test_exit_hook_checks_even_after_failure_and_preserves_status(tmp_path, code):
    source = (ROOT / "scripts/run_daily.sh").read_text()
    functions = source[source.index("check_openai_balance() {"):source.index("trap on_error ERR")]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "logs").mkdir()
    (scripts / "check_openai_balance.sh").write_text('echo "CHECKED"; exit 1\n')
    command = f'ROOT_DIR="{tmp_path}"; LOG_DIR="{tmp_path}/logs"\n' + functions
    command += f'\ntrap on_exit EXIT\nexit {code}\n'
    result = subprocess.run(["bash", "-c", command], capture_output=True)
    assert result.returncode == code
    assert (tmp_path / "logs/openai_balance.log").read_text().strip() == "CHECKED"


@pytest.mark.parametrize("curl_status,strict,expected", [(0, "1", 0), (22, "1", 1), (22, "0", 0)])
def test_webhook_delivery_status(tmp_path, curl_status, strict, expected):
    curl = tmp_path / "curl"
    curl.write_text(f'#!/bin/sh\nexit {curl_status}\n')
    curl.chmod(0o755)
    (tmp_path / "python").symlink_to(sys.executable)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
               ALERT_WEBHOOK_SLACK="https://example.invalid", ALERT_WEBHOOK_DISCORD="",
               ALERT_REQUIRE_DELIVERY=strict)
    result = subprocess.run(["bash", str(ROOT / "scripts/notify_webhooks.sh"), "test", "warning"],
                            env=env, capture_output=True)
    assert result.returncode == expected
