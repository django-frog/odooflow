import json
import pytest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from odooflow.cli import app

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def temp_dir_with_env(tmp_path):
    env_path = tmp_path / ".odooflow.env.json"
    env_path.write_text('{"name": "test", "remotes": {}}')
    return tmp_path

class TestRemoteCommand:
    def test_remote_add_repo(self, runner, temp_dir_with_env):
        with patch("pathlib.Path.cwd", return_value=temp_dir_with_env):
            with patch("odooflow.commands.remote.get_current_branch", return_value="main"):
                result = runner.invoke(app, ["remote", "--add-repo", "https://gitlab.com/test/repo.git"])
                assert result.exit_code == 0
                env = json.loads((temp_dir_with_env / ".odooflow.env.json").read_text())
                assert env["remotes"]["repo"]["url"] == "https://gitlab.com/test/repo.git"

    def test_remote_add_server(self, runner, temp_dir_with_env):
        with patch("pathlib.Path.cwd", return_value=temp_dir_with_env):
            result = runner.invoke(app, ["remote", "--server-json", '{"host": "127.0.0.1", "port": 22, "user": "test", "directory": "/opt/odoo"}'])
            assert result.exit_code == 0
            env = json.loads((temp_dir_with_env / ".odooflow.env.json").read_text())
            assert env["remotes"]["server"]["host"] == "127.0.0.1"
