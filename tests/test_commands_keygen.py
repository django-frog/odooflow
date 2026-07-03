import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from odooflow.cli import app

@pytest.fixture
def runner():
    return CliRunner()

class TestKeygenCommand:
    def test_keygen_basic(self, runner, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run") as mock_run:
                result = runner.invoke(app, ["ssh-keygen"])
                assert result.exit_code == 0
                mock_run.assert_called_once()

    def test_keygen_with_custom_name(self, runner, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run"):
                result = runner.invoke(app, ["ssh-keygen", "--key-name", "custom_key"])
                assert result.exit_code == 0
