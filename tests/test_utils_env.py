import json
import pytest
from pathlib import Path
from unittest.mock import patch
import typer

from odooflow import errors
from odooflow.utils.env import (
    read_manifest,
    update_manifest,
    write_env_file,
    read_env_file,
)


@pytest.fixture
def temp_manifest_file(tmp_path):
    """Create a temporary manifest file for testing."""
    manifest_path = tmp_path / "__manifest__.py"
    return manifest_path


@pytest.fixture
def temp_env_file(tmp_path):
    """Create a temporary env file for testing."""
    env_path = tmp_path / ".odooflow.env.json"
    return env_path


class TestEnvUtils:
    """Test cases for env utility functions."""

    def test_read_manifest_valid(self, temp_manifest_file):
        """Test reading a valid manifest file."""
        manifest_content = "{'name': 'test_module', 'version': '16.0'}"
        temp_manifest_file.write_text(manifest_content)

        manifest = read_manifest(temp_manifest_file)
        assert manifest == {"name": "test_module", "version": "16.0"}

    def test_read_manifest_invalid_syntax(self, temp_manifest_file):
        """Syntax errors raise ConfigError (no silent fallback)."""
        temp_manifest_file.write_text("invalid python")

        with pytest.raises(errors.ConfigError):
            read_manifest(temp_manifest_file)

    def test_read_manifest_empty_file(self, temp_manifest_file):
        """An empty manifest is a syntax error — raises ConfigError."""
        temp_manifest_file.write_text("")

        with pytest.raises(errors.ConfigError):
            read_manifest(temp_manifest_file)

    def test_read_manifest_security(self, temp_manifest_file):
        """eval must not be used: malicious content raises ConfigError."""
        malicious_content = "__import__('os').system('echo malicious')"
        temp_manifest_file.write_text(malicious_content)

        with pytest.raises(errors.ConfigError):
            read_manifest(temp_manifest_file)

    def test_write_env_file(self, temp_env_file):
        """Test writing env file."""
        test_values = {
            "name": "test_module",
            "author": "Test Author",
            "version": "16.0"
        }
        write_env_file(temp_env_file, test_values)

        assert temp_env_file.exists()
        loaded = json.loads(temp_env_file.read_text())
        assert loaded == test_values

    def test_read_env_file_valid(self, temp_env_file):
        """Test reading a valid env file."""
        test_values = {"name": "test_module", "version": "16.0"}
        temp_env_file.write_text(json.dumps(test_values))

        env = read_env_file(temp_env_file)
        assert env == test_values

    def test_read_env_file_invalid_json(self, temp_env_file):
        """Invalid JSON returns {} and prints a hint."""
        temp_env_file.write_text("invalid json")
        env = read_env_file(temp_env_file)
        assert env == {}

    def test_read_env_file_not_exists(self, temp_env_file):
        """Test reading env file that doesn't exist."""
        assert not temp_env_file.exists()
        env = read_env_file(temp_env_file)
        assert env == {}

    def test_update_manifest(self, temp_manifest_file):
        """Test updating manifest file."""
        initial_content = "{'name': 'test_module', 'version': '16.0'}"
        temp_manifest_file.write_text(initial_content)

        updates = {"author": "Test Author", "license": "LGPL-3"}
        update_manifest(temp_manifest_file, updates)

        updated_content = temp_manifest_file.read_text()
        assert "Test Author" in updated_content
        assert "LGPL-3" in updated_content
