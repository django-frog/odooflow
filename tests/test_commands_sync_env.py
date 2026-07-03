import json
import pytest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner

from odooflow.cli import app


@pytest.fixture
def runner():
    """Create a CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def temp_dir_with_files(tmp_path):
    """Create a temporary directory with manifest and env files."""
    manifest_content = """{
    'name': 'test_module',
    'version': '16.0',
    'author': 'Test Author',
    'license': 'LGPL-3',
    'depends': ['base', 'web']
}"""
    manifest_path = tmp_path / "__manifest__.py"
    manifest_path.write_text(manifest_content)
    
    env_content = """{
    "name": "old_name",
    "version": "15.0"
}"""
    env_path = tmp_path / ".odooflow.env.json"
    env_path.write_text(env_content)
    
    return tmp_path


class TestSyncEnv:
    """Test cases for sync-env command."""

    def test_sync_env_default_keys(self, runner, temp_dir_with_files):
        """Test sync-env with default keys."""
        with patch("pathlib.Path.cwd", return_value=temp_dir_with_files):
            result = runner.invoke(app, ["sync-env"])
            assert result.exit_code == 0
            
            env_path = temp_dir_with_files / ".odooflow.env.json"
            env = json.loads(env_path.read_text())
            assert env["name"] == "test_module"
            assert env["version"] == "16.0"
            assert env["author"] == "Test Author"

    def test_sync_env_custom_keys(self, runner, temp_dir_with_files):
        """Test sync-env with custom keys."""
        with patch("pathlib.Path.cwd", return_value=temp_dir_with_files):
            result = runner.invoke(app, ["sync-env", "--keys", "name,license"])
            assert result.exit_code == 0
            
            env_path = temp_dir_with_files / ".odooflow.env.json"
            env = json.loads(env_path.read_text())
            assert env["name"] == "test_module"
            assert env["license"] == "LGPL-3"
            assert env["version"] == "15.0"  # Should not be updated

    def test_sync_env_no_manifest(self, runner, tmp_path):
        """Test sync-env without manifest file."""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["sync-env"])
            assert result.exit_code == 1
