from __future__ import annotations

from pathlib import Path

import pytest

from lloyds_digest.config import load_config


def test_load_config_with_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'topics_csv: "base"',
                "cache:",
                "  enabled: false",
                "output:",
                "  enabled: true",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LLOYDS_DIGEST__CACHE__ENABLED", "true")

    config = load_config(config_path)

    assert config.topics_csv == "base"
    assert config.cache.enabled is True
    assert config.output.enabled is True


def test_load_config_invalid_bool(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'topics_csv: "base"',
                "cache:",
                "  enabled: maybe",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid boolean value"):
        load_config(config_path)
