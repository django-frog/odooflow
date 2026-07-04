from unittest.mock import patch, MagicMock

import pytest

from odooflow.commands.gitlab import (
    extract_project_path_from_url,
    get_default_branch,
)
from odooflow import errors


class TestProjectPathExtraction:
    def test_simple_https_url(self):
        assert (
            extract_project_path_from_url(
                "https://gitlab.ebtech-solution.com/ebtech/internal/ebt_hr_attendance"
            )
            == "ebtech/internal/ebt_hr_attendance"
        )

    def test_trailing_git_suffix_stripped(self):
        assert (
            extract_project_path_from_url(
                "https://gitlab.ebtech-solution.com/group/proj.git"
            )
            == "group/proj"
        )

    def test_trailing_slash_stripped(self):
        assert (
            extract_project_path_from_url(
                "https://gitlab.ebtech-solution.com/group/proj/"
            )
            == "group/proj"
        )

    def test_no_path_returns_none(self):
        assert extract_project_path_from_url("https://gitlab.ebtech-solution.com") is None


class TestGetDefaultBranch:
    def _ok_response(self, default_branch="master"):
        resp = MagicMock()
        resp.json.return_value = {"default_branch": default_branch}
        resp.raise_for_status = MagicMock()
        return resp

    def _err_response(self, exc):
        resp = MagicMock()
        resp.raise_for_status = MagicMock(side_effect=exc)
        return resp

    def test_returns_default_branch_when_api_succeeds(self):
        with patch("odooflow.commands.gitlab.requests.get",
                   return_value=self._ok_response("master")) as gget, \
             patch("odooflow.commands.gitlab.get_access_token",
                   return_value="glpat-fake"):
            result = get_default_branch(
                "https://gitlab.ebtech-solution.com/ebtech/internal/ebt_hr_attendance"
            )
        assert result == "master"
        # path is URL-encoded once
        args, kwargs = gget.call_args
        assert "ebtech%2Finternal%2Febt_hr_attendance" in args[0]

    def test_returns_default_branch_main(self):
        with patch("odooflow.commands.gitlab.requests.get",
                   return_value=self._ok_response("main")), \
             patch("odooflow.commands.gitlab.get_access_token",
                   return_value="glpat-fake"):
            assert get_default_branch(
                "https://gitlab.ebtech-solution.com/g/p"
            ) == "main"

    def test_network_failure_returns_none(self):
        import requests
        with patch("odooflow.commands.gitlab.requests.get",
                   return_value=self._err_response(
                       requests.ConnectionError("dns down")
                   )), \
             patch("odooflow.commands.gitlab.get_access_token",
                   return_value="glpat-fake"):
            assert get_default_branch(
                "https://gitlab.ebtech-solution.com/g/p"
            ) is None

    def test_no_token_returns_none(self):
        with patch(
            "odooflow.commands.gitlab.get_access_token",
            side_effect=errors.AccessTokenMissingError(rc_path=MagicMock()),
        ):
            assert get_default_branch(
                "https://gitlab.ebtech-solution.com/g/p"
            ) is None

    def test_empty_default_branch_returns_none(self):
        with patch("odooflow.commands.gitlab.requests.get",
                   return_value=self._ok_response("")), \
             patch("odooflow.commands.gitlab.get_access_token",
                   return_value="glpat-fake"):
            assert get_default_branch(
                "https://gitlab.ebtech-solution.com/g/p"
            ) is None

    def test_url_without_path_returns_none(self):
        with patch("odooflow.commands.gitlab.get_access_token",
                   return_value="glpat-fake"):
            assert get_default_branch(
                "https://gitlab.ebtech-solution.com"
            ) is None
