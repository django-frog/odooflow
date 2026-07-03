import json
import pytest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner

from odooflow.cli import app
from odooflow import config_manager


@pytest.fixture
def runner():
    """Create a CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file for testing."""
    config_path = tmp_path / ".odooflowrc"
    return config_path


@pytest.fixture
def mock_home(tmp_path, temp_config_file):
    """Mock home directory."""
    with patch("odooflow.config_manager.Path.home", return_value=tmp_path):
        yield tmp_path


class TestConfigCommand:
    """Test cases for config command."""

    def test_config_show_default(self, runner, mock_home):
        """Test showing default configuration."""
        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 0
        assert "env_file" in result.stdout

    def test_config_show_custom(self, runner, mock_home, temp_config_file):
        """Test showing custom configuration."""
        test_config = {
            "env_file": ".custom.env.json",
            "manifest_file": "__openerp__.py"
        }
        temp_config_file.write_text(json.dumps(test_config))
        
        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 0
        assert ".custom.env.json" in result.stdout

    def test_config_set_env_file(self, runner, mock_home):
        """Test setting env_file in config."""
        result = runner.invoke(app, ["config", "--env-file", ".test.env.json"])
        assert result.exit_code == 0
        assert "Configuration updated" in result.stdout
        
        config = config_manager.load_config()
        assert config["env_file"] == ".test.env.json"

    def test_config_set_manifest_file(self, runner, mock_home):
        """Test setting manifest_file in config."""
        result = runner.invoke(app, ["config", "--manifest-file", "__openerp__.py"])
        assert result.exit_code == 0
        assert "Configuration updated" in result.stdout
        
        config = config_manager.load_config()
        assert config["manifest_file"] == "__openerp__.py"

    def test_config_set_access_token(self, runner, mock_home):
        """Test setting access token in config."""
        result = runner.invoke(app, ["config", "--access-token", "test_token_123"])
        assert result.exit_code == 0
        assert "Configuration updated" in result.stdout
        
        config = config_manager.load_config()
        assert config["access_token"] == "test_token_123"

    def test_config_add_core_module(self, runner, mock_home):
        """Test adding core modules to config."""
        result = runner.invoke(app, ["config", "--add-core-module", "sale,purchase"])
        assert result.exit_code == 0
        assert "Added core module" in result.stdout
        
        config = config_manager.load_config()
        assert "sale" in config["core_modules"]
        assert "purchase" in config["core_modules"]

    def test_config_set_sync_keys(self, runner, mock_home):
        """Test setting sync keys in config."""
        result = runner.invoke(app, ["config", "--sync-keys", "name,version,author"])
        assert result.exit_code == 0
        assert "Updated sync keys" in result.stdout
        
        config = config_manager.load_config()
        assert "name" in config["sync_keys"]
        assert "version" in config["sync_keys"]
        assert "author" in config["sync_keys"]

    def test_config_no_changes(self, runner, mock_home):
        """Test config command with no changes."""
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "No changes provided" in result.stdout
