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
def temp_dir(tmp_path):
    """Create a temporary directory with manifest file."""
    manifest_content = """{
    'name': 'test_module',
    'version': '16.0',
    'author': 'Default Author',
    'license': 'LGPL-3',
    'website': 'https://example.com',
    'depends': ['base', 'web']
}"""
    manifest_path = tmp_path / "__manifest__.py"
    manifest_path.write_text(manifest_content)
    return tmp_path


class TestInitModuleEnv:
    """Test cases for init command."""

    def test_init_with_all_params(self, runner, temp_dir):
        """Test init command with all parameters."""
        with patch("pathlib.Path.cwd", return_value=temp_dir):
            result = runner.invoke(app, [
                "init",
                "--author", "Test Author",
                "--odoo-version", "17.0",
                "--license-name", "MIT",
                "--website", "https://test.com"
            ])
            assert result.exit_code == 0

            env_path = temp_dir / ".odooflow.env.json"
            assert env_path.exists()

            env = json.loads(env_path.read_text())
            assert env["author"] == "Test Author"
            assert env["version"] == "17.0"
            assert env["license"] == "MIT"
            assert env["website"] == "https://test.com"

    def test_init_without_manifest(self, runner, tmp_path):
        """Test init command without manifest file."""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["init"])
            assert result.exit_code == 1

    def test_init_partial_params(self, runner, temp_dir):
        """Test init command with partial parameters."""
        with patch("pathlib.Path.cwd", return_value=temp_dir):
            result = runner.invoke(app, [
                "init",
                "--author", "Test Author"
            ])
            assert result.exit_code == 0
            
            env_path = temp_dir / ".odooflow.env.json"
            env = json.loads(env_path.read_text())
            assert env["author"] == "Test Author"
            assert env["version"] == "16.0"  # Default from manifest
