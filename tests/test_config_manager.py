import json
import pytest
from pathlib import Path
from unittest.mock import patch

from odooflow import errors
from odooflow.config_manager import (
    DEFAULT_CONFIG,
    get_global_config_path,
    load_config,
    save_config,
    get_access_token,
    get_core_modules_from_config,
)


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file for testing."""
    config_path = tmp_path / ".odooflowrc"
    return config_path


@pytest.fixture
def mock_home(tmp_path):
    """Mock home directory."""
    from odooflow import config_manager
    config_manager.reset_printed_notices()
    with patch("odooflow.config_manager.Path.home", return_value=tmp_path):
        yield tmp_path
    config_manager.reset_printed_notices()


class TestConfigManager:
    """Test cases for config_manager module."""

    def test_default_config_structure(self):
        """Test that DEFAULT_CONFIG has all required keys."""
        assert "env_file" in DEFAULT_CONFIG
        assert "manifest_file" in DEFAULT_CONFIG
        assert "core_modules" in DEFAULT_CONFIG
        assert "sync_keys" in DEFAULT_CONFIG
        assert "gitlab_url" in DEFAULT_CONFIG

    def test_get_global_config_path(self, mock_home):
        """Test getting global config path."""
        path = get_global_config_path()
        assert path == mock_home / ".odooflowrc"

    def test_load_config_no_file(self, mock_home, capsys):
        """When no rc exists, defaults are used and a soft hint is printed."""
        config = load_config()
        assert config == DEFAULT_CONFIG
        captured = capsys.readouterr()
        assert "No configuration file found" in captured.err

    def test_load_config_with_file(self, mock_home, temp_config_file):
        """Test loading config from existing file."""
        test_config = {
            "env_file": ".custom.env.json",
            "manifest_file": "__openerp__.py",
            "core_modules": ["base", "web"],
            "sync_keys": ["name", "version"],
            "gitlab_url": "https://custom.gitlab.com"
        }
        temp_config_file.write_text(json.dumps(test_config))

        config = load_config()
        assert config == test_config

    def test_load_config_invalid_json_recovers(self, mock_home, temp_config_file, capsys):
        """
        Invalid JSON no longer exits: the rc is backed up and defaults are
        returned so the user is not blocked. A clear 'how to fix' message is
        printed.
        """
        temp_config_file.write_text("invalid json")
        config = load_config()

        assert config == DEFAULT_CONFIG
        assert not temp_config_file.exists(), "corrupt rc should have been moved aside"
        backups = list(mock_home.glob(".odooflowrc.corrupt.*"))
        assert len(backups) == 1
        assert backups[0].read_text() == "invalid json"

        captured = capsys.readouterr()
        assert "corrupted" in captured.err

    def test_load_config_empty_file_recovers(self, mock_home, temp_config_file, capsys):
        """Empty rc file is treated like a corrupt file: backed up + defaults."""
        temp_config_file.write_text("")
        config = load_config()
        assert config == DEFAULT_CONFIG
        assert not temp_config_file.exists()
        assert list(mock_home.glob(".odooflowrc.corrupt.*"))

    def test_load_config_shape_error_recovers(self, mock_home, temp_config_file):
        """Top-level scalar/list JSON is rejected, backed up, defaults returned."""
        temp_config_file.write_text('"oops just a string"')
        config = load_config()
        assert config == DEFAULT_CONFIG
        assert not temp_config_file.exists()

    def test_load_config_strict_raises_on_problems(self, mock_home, temp_config_file):
        """strict=True should propagate the error to callers that want to fail fast."""
        temp_config_file.write_text("not json")
        with pytest.raises(errors.ConfigError):
            load_config(strict=True)

    def test_save_config(self, mock_home, temp_config_file):
        """Test saving config to file."""
        test_config = {"env_file": ".test.env.json"}
        save_config(test_config)

        assert temp_config_file.exists()
        loaded = json.loads(temp_config_file.read_text())
        assert loaded == test_config

    def test_get_access_token_from_env(self, mock_home):
        """Test getting access token from environment variable."""
        with patch.dict("os.environ", {"ODOOFLOW_ACCESS_TOKEN": "test_token"}):
            token = get_access_token()
            assert token == "test_token"

    def test_get_access_token_from_config(self, mock_home, temp_config_file):
        """Test getting access token from config file."""
        test_config = {"access_token": "config_token"}
        temp_config_file.write_text(json.dumps(test_config))

        with patch.dict("os.environ", {}, clear=True):
            token = get_access_token()
            assert token == "config_token"

    def test_get_access_token_not_found(self, mock_home):
        """Test getting access token when not found — raises ConfigError subclass."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(errors.AccessTokenMissingError):
                get_access_token()

    def test_get_core_modules_from_config_default(self, mock_home):
        """Test getting core modules with default config."""
        modules = get_core_modules_from_config()
        assert modules == set(DEFAULT_CONFIG["core_modules"])

    def test_get_core_modules_from_config_custom(self, mock_home, temp_config_file):
        """Test getting core modules with custom config."""
        test_config = {
            "core_modules": ["base", "web", "custom"]
        }
        temp_config_file.write_text(json.dumps(test_config))

        modules = get_core_modules_from_config()
        assert modules == {"base", "web", "custom"}

    def test_get_core_modules_from_config_empty(self, mock_home, temp_config_file):
        """Test getting core modules when config has empty list."""
        test_config = {"core_modules": []}
        temp_config_file.write_text(json.dumps(test_config))

        modules = get_core_modules_from_config()
        assert modules == set()

    def test_is_configured_true_when_env_set(self, mock_home):
        with patch.dict("os.environ", {"ODOOFLOW_ACCESS_TOKEN": "x"}):
            from odooflow.config_manager import is_configured
            assert is_configured() is True

    def test_is_configured_false_when_no_token(self, mock_home):
        with patch.dict("os.environ", {}, clear=True):
            from odooflow.config_manager import is_configured
            assert is_configured() is False
