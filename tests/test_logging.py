from __future__ import annotations

import json
from pathlib import Path

from lloyds_digest.reporting.logging import log_event


def test_log_event_writes_json(tmp_path: Path, capsys) -> None:
    log_path = tmp_path / "run.jsonl"
    log_event("test", {"value": 1}, log_path)

    captured = capsys.readouterr().out.strip()
    assert json.loads(captured)["event"] == "test"

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["value"] == 1
