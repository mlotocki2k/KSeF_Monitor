"""
Unit tests for SecretsManager
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.secrets_manager import SecretsManager


class TestSecretsManagerGetSecret:
    """Tests for get_secret() priority chain."""

    def test_env_var_takes_priority(self):
        """Environment variable takes priority over Docker secret."""
        sm = SecretsManager("/nonexistent/config.json")
        with patch.dict("os.environ", {"KSEF_TOKEN": "env-token"}):
            assert sm.get_secret("KSEF_TOKEN") == "env-token"

    def test_docker_secret_fallback(self, tmp_path):
        """Docker secret is used when env var is not set."""
        sm = SecretsManager("/nonexistent/config.json")
        sm.docker_secrets_path = tmp_path

        secret_file = tmp_path / "ksef_token"
        secret_file.write_text("docker-secret-token\n")

        with patch.dict("os.environ", {}, clear=True):
            assert sm.get_secret("KSEF_TOKEN") == "docker-secret-token"

    def test_default_when_no_sources(self):
        """Returns default when neither env var nor Docker secret available."""
        sm = SecretsManager("/nonexistent/config.json")
        sm.docker_secrets_path = Path("/nonexistent/secrets")

        with patch.dict("os.environ", {}, clear=True):
            assert sm.get_secret("MISSING_KEY", default="fallback") == "fallback"

    def test_none_when_no_default(self):
        """Returns None when no secret found and no default."""
        sm = SecretsManager("/nonexistent/config.json")
        sm.docker_secrets_path = Path("/nonexistent/secrets")

        with patch.dict("os.environ", {}, clear=True):
            assert sm.get_secret("MISSING_KEY") is None


class TestSecretsManagerLoadConfigWithSecrets:
    """Tests for load_config_with_secrets()."""

    def test_load_and_inject(self, tmp_path, minimal_config):
        """Config is loaded and secrets are injected."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(minimal_config), encoding="utf-8")

        sm = SecretsManager(str(config_path))
        sm.docker_secrets_path = Path("/nonexistent/secrets")

        with patch.dict("os.environ", {"KSEF_TOKEN": "injected-token"}, clear=True):
            config = sm.load_config_with_secrets()
            assert config["ksef"]["token"] == "injected-token"

    def test_missing_config_raises(self):
        """Missing config file raises FileNotFoundError."""
        sm = SecretsManager("/nonexistent/config.json")
        with pytest.raises(FileNotFoundError):
            sm.load_config_with_secrets()

    def test_invalid_json_raises(self, tmp_path):
        """Invalid JSON raises JSONDecodeError."""
        config_path = tmp_path / "config.json"
        config_path.write_text("{bad json", encoding="utf-8")

        sm = SecretsManager(str(config_path))
        with pytest.raises(json.JSONDecodeError):
            sm.load_config_with_secrets()


class TestSecretsManagerInjectSecrets:
    """Tests for _inject_secrets()."""

    def test_inject_pushover_secrets(self, tmp_path, minimal_config):
        """Pushover secrets are injected into both old and new structures."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(minimal_config), encoding="utf-8")

        sm = SecretsManager(str(config_path))
        sm.docker_secrets_path = Path("/nonexistent")

        env = {
            "PUSHOVER_USER_KEY": "env-user",
            "PUSHOVER_API_TOKEN": "env-token"
        }
        with patch.dict("os.environ", env, clear=True):
            result = sm._inject_secrets(minimal_config.copy())
            assert result["notifications"]["pushover"]["user_key"] == "env-user"
            assert result["notifications"]["pushover"]["api_token"] == "env-token"

    def test_inject_discord_secret(self, tmp_path, minimal_config):
        """Discord webhook URL is injected."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(minimal_config), encoding="utf-8")

        sm = SecretsManager(str(config_path))
        sm.docker_secrets_path = Path("/nonexistent")

        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": "https://discord.hook"}, clear=True):
            result = sm._inject_secrets({})
            assert result["notifications"]["discord"]["webhook_url"] == "https://discord.hook"

    def test_inject_webhook_token(self, tmp_path, minimal_config):
        """Webhook token is injected into Authorization header."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(minimal_config), encoding="utf-8")

        sm = SecretsManager(str(config_path))
        sm.docker_secrets_path = Path("/nonexistent")

        with patch.dict("os.environ", {"WEBHOOK_TOKEN": "my-bearer-token"}, clear=True):
            result = sm._inject_secrets({})
            assert result["notifications"]["webhook"]["headers"]["Authorization"] == "Bearer my-bearer-token"


class TestSecretsManagerValidateSecrets:
    """Tests for validate_secrets()."""

    def test_all_present(self, tmp_path, minimal_config):
        """Returns True when all required secrets present."""
        sm = SecretsManager(str(tmp_path / "c.json"))
        config = {
            "ksef": {"token": "t"},
            "pushover": {"user_key": "u", "api_token": "a"}
        }
        assert sm.validate_secrets(config) is True

    def test_missing_token(self, tmp_path):
        """Returns False when ksef token missing."""
        sm = SecretsManager(str(tmp_path / "c.json"))
        config = {
            "ksef": {},
            "pushover": {"user_key": "u", "api_token": "a"}
        }
        assert sm.validate_secrets(config) is False
