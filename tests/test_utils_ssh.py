import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from odooflow.utils.ssh import resolve_remote_path, compress_directory

class TestSSHUtils:
    def test_resolve_remote_path_absolute(self):
        sftp = MagicMock()
        sftp.normalize.return_value = "/home/user"
        result = resolve_remote_path(sftp, "/opt/odoo")
        assert result == "/opt/odoo"

    def test_resolve_remote_path_relative(self):
        sftp = MagicMock()
        sftp.normalize.return_value = "/home/user"
        result = resolve_remote_path(sftp, "odoo")
        assert result == "/home/user/odoo"

    def test_resolve_remote_path_tilde(self):
        sftp = MagicMock()
        sftp.normalize.return_value = "/home/user"
        result = resolve_remote_path(sftp, "~/odoo")
        assert result == "/home/user/odoo"
