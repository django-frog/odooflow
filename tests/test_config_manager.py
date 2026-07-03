import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import typer

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
    with patch("odooflow.config_manager.Path.home", return_value=tmp_path):
        yield tmp_path


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

    def test_load_config_no_file(self, mock_home):
        """Test loading config when no config file exists."""
        config = load_config()
        assert config == DEFAULT_CONFIG

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

    def test_load_config_invalid_json(self, mock_home, temp_config_file):
        """Test loading config with invalid JSON exits with an error (no silent fallback)."""
        temp_config_file.write_text("invalid json")
        with pytest.raises(typer.Exit):
            load_config()

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
        """Test getting access token when not found."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(typer.Exit):
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
