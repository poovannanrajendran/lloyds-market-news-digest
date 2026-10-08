#!/usr/bin/env python3
"""Estimate prepaid credit from a reconciled balance and organisation-wide costs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def number(value: str) -> Decimal:
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Non-finite monetary value")
    return result


def fetch_costs(key: str, start: int, end: int) -> Decimal:
    """Include every project, model and line item; follow all result pages."""
    total = Decimal(0)
    page = None
    seen = set()
    for _ in range(100):
        params = {"start_time": start, "end_time": end, "limit": 180}
        if page:
            params["page"] = page
        request = urllib.request.Request(
            "https://api.openai.com/v1/organization/costs?" + urllib.parse.urlencode(params),
            headers={"Authorization": "Bearer " + key},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response, parse_float=Decimal)
        if not isinstance(payload.get("data"), list) or not isinstance(payload.get("has_more"), bool):
            raise ValueError("Unexpected Costs API response")
        for bucket in payload["data"]:
            for result in bucket["results"]:
                amount = result["amount"]
                if amount["currency"] != "usd":
                    raise ValueError("Costs API returned a non-USD amount")
                total += number(str(amount["value"]))
        if not payload["has_more"]:
            return total
        page = payload.get("next_page")
        if not page or page in seen:
            raise ValueError("Invalid Costs API pagination")
        seen.add(page)
    raise ValueError("Costs API pagination limit exceeded")


def remaining(balance: Decimal, baseline_cost: Decimal, current_cost: Decimal) -> Decimal:
    if current_cost < baseline_cost:
        raise ValueError("Reported costs fell below the baseline; reconcile billing")
    return balance - (current_cost - baseline_cost)


def notify(message: str, level: str) -> bool:
    env = dict(os.environ, ALERT_REQUIRE_DELIVERY="1")
    # Use the same Python runtime for the transport's JSON encoding.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/notify_webhooks.sh"), message, level],
        env=env, capture_output=True, timeout=50,
    )
    return result.returncode == 0


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".openai-balance-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def check(env: dict, state_path: Path, dry_run: bool = False, fetch=fetch_costs, send=notify) -> int:
    now = int(time.time())
    today = datetime.fromtimestamp(now, ZoneInfo("Europe/London")).date().isoformat()
    state = {}
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if not isinstance(state, dict):
                state = {}
                raise ValueError("Invalid checker state")
        balance = number(env["OPENAI_BALANCE_BASELINE_USD"])
        baseline = number(env["OPENAI_COSTS_BASELINE_USD"])
        threshold = number(env.get("OPENAI_BALANCE_ALERT_THRESHOLD_USD", "1"))
        start = int(env["OPENAI_COSTS_START_TIME"])
        key = env["OPENAI_API_ADMIN_KEY"]
        if balance < 0 or baseline < 0 or threshold < 0 or not key or not 0 < start < now:
            raise ValueError("Invalid baseline or credentials configuration")
        fingerprint = hashlib.sha256(f"{balance}|{baseline}|{threshold}|{start}".encode()).hexdigest()
        if state.get("baseline_fingerprint") != fingerprint:
            state = {"baseline_fingerprint": fingerprint}
        current = fetch(key, start, now)
        credit = remaining(balance, baseline, current)
    except Exception as exc:
        # Never log response bodies, URLs, credentials or arbitrary exception text.
        reason = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        message = (
            f"OpenAI estimated-balance check unavailable ({reason}). Cannot verify the $1 reserve; "
            "check billing and the balance baseline. The daily pipeline will continue."
        )
        print("openai-balance: unavailable; " + reason)
        if dry_run:
            print("DRY RUN: " + message)
        elif state.get("error_alert_date") != today:
            if send(message, "warning"):
                state["error_alert_date"] = today
                save_state(state_path, state)
            else:
                print("openai-balance: warning delivery failed; will retry on the next check")
        return 1
    state.update(checked_at=now, reported_cost_usd=str(current), estimated_balance_usd=str(credit))
    state.pop("error_alert_date", None)
    low = credit <= threshold
    print(f"openai-balance: estimated_remaining_usd={credit:.6f} threshold_usd={threshold} low={low}")
    if low:
        message = (
            f"OpenAI estimated API credit balance is ${credit:.4f} (at or below ${threshold:.2f}). "
            f"Reported spend since the ${balance:.2f} balance baseline: ${current - baseline:.4f}. "
            "Please top up and reset the baseline. Costs may lag usage; this is an estimate."
        )
        if dry_run:
            print("DRY RUN: " + message)
        elif state.get("low_alert_date") != today:
            if send(message, "warning"):
                state["low_alert_date"] = today
            else:
                print("openai-balance: warning delivery failed; will retry on the next check")
                save_state(state_path, state)
                return 1
    else:
        state.pop("low_alert_date", None)
    if not dry_run:
        save_state(state_path, state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Read costs without alerts or state writes")
    args = parser.parse_args()
    try:
        # Protect deduplication against overlapping daily and manual checks.
        import fcntl
        path = ROOT / "logs/openai_balance_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / "openai_balance.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return check(dict(os.environ), path, args.dry_run)
    except Exception as exc:
        print("openai-balance: checker failed; " + type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
