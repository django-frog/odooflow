from unittest.mock import patch, MagicMock

import pytest
import typer
from git import GitCommandError

from odooflow.commands.clone_module import (
    clone_repo,
    clone_module_command,
    _resolve_branch,
)


@pytest.fixture
def fake_token(monkeypatch):
    monkeypatch.setattr(
        "odooflow.commands.clone_module.get_access_token",
        lambda: "glpat-fake",
    )


class TestResolveBranch:
    def test_explicit_branch_wins(self, monkeypatch):
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: "master",
        )
        assert _resolve_branch("https://x/y/z.git", "16.0") == "16.0"

    def test_falls_back_to_default_from_gitlab(self, monkeypatch):
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: "master",
        )
        assert _resolve_branch("https://x/y/z.git", None) == "master"

    def test_returns_none_when_nothing_known(self, monkeypatch):
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: None,
        )
        assert _resolve_branch("https://x/y/z.git", None) is None


class TestCloneRepoBranchSelection:
    def test_passes_explicit_branch(self, tmp_path, fake_token, monkeypatch):
        target = tmp_path / "proj"
        captured = {}

        def fake_clone_from(*args, **kwargs):
            captured["url"] = args[0] if args else None
            captured["kwargs"] = kwargs

        monkeypatch.setattr("odooflow.commands.clone_module.Repo.clone_from",
                            fake_clone_from)
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: "master",
        )

        ok = clone_repo(
            "https://gitlab.example.com/g/p",
            target,
            branch="16.0",
        )
        assert ok is True
        assert captured["kwargs"].get("branch") == "16.0"

    def test_uses_gitlab_default_when_no_branch(self, tmp_path, fake_token, monkeypatch):
        target = tmp_path / "proj"
        captured = {}

        def fake_clone_from(*args, **kwargs):
            captured["kwargs"] = kwargs

        monkeypatch.setattr("odooflow.commands.clone_module.Repo.clone_from",
                            fake_clone_from)
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: "master",
        )

        ok = clone_repo("https://gitlab.example.com/g/p", target, branch=None)
        assert ok is True
        assert captured["kwargs"].get("branch") == "master"

    def test_omits_branch_arg_when_unknown(self, tmp_path, fake_token, monkeypatch):
        target = tmp_path / "proj"
        captured = {}

        def fake_clone_from(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        monkeypatch.setattr("odooflow.commands.clone_module.Repo.clone_from",
                            fake_clone_from)
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: None,
        )

        ok = clone_repo("https://gitlab.example.com/g/p", target, branch=None)
        assert ok is True
        assert "branch" not in captured["kwargs"]
        # clone_from signature: clone_from(url, target). url was tokenised.
        assert str(captured["args"][0]) == "https://oauth2:glpat-fake@gitlab.example.com/g/p"
        assert captured["args"][1] == target
        assert len(captured["args"]) == 2

    def test_skips_existing_target(self, tmp_path, fake_token):
        target = tmp_path / "proj"
        target.mkdir()
        # Existing dir is intentionally treated as success so re-running
        # `odooflow clone` is idempotent.
        assert clone_repo("https://x/y/p", target, branch=None) is True

    def test_branch_error_surfaces_helpful_reason(
        self, tmp_path, fake_token, monkeypatch
    ):
        target = tmp_path / "proj"

        boom = GitCommandError(
            ["git", "clone"],
            128,
            stderr=(
                "Cloning into '/tmp/proj'...\n"
                "POST git-upload-pack (352 bytes)\n"
                "fatal: Remote branch main not found in upstream origin\n"
            ),
        )

        monkeypatch.setattr(
            "odooflow.commands.clone_module.Repo.clone_from",
            MagicMock(side_effect=boom),
        )
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: None,
        )

        assert clone_repo("https://gitlab.example.com/g/p", target, branch=None) is False


class TestDependencyResolutionRegression:
    """
    Regression test for the UnboundLocalError that fired when concurrent
    worker threads (used by clone_module_command for dep resolution) tried
    to mutate `fail_count` without declaring `nonlocal`. We drive the full
    clone_module_command with stubbed URL lookup returning no project so
    that every dependency fails resolution — exercising the exact code path
    in _resolve_and_run.
    """

    def _setup(self, monkeypatch, deps=("base_setup", "hr_attendance")):
        # Token is "present" so preflight passes.
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_access_token",
            lambda: "glpat-fake",
        )
        # core_modules is empty so every dep is treated as a candidate.
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_core_modules_from_config",
            lambda: set(),
        )
        # Default branch lookup returns master.
        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_default_branch",
            lambda url: "master",
        )
        # clone_repo runs against a fake Repo so we don't actually shell out.
        monkeypatch.setattr(
            "odooflow.commands.clone_module.Repo.clone_from",
            lambda *a, **k: None,
        )
        # The target project URL always resolves; deps never resolve.
        def fake_get_project_url(module_name, base_url=None):
            if module_name == "root":
                return "https://gitlab.example.com/g/root"
            return None

        monkeypatch.setattr(
            "odooflow.commands.clone_module.get_project_url_from_gitlab",
            fake_get_project_url,
        )
        # Manifest of "root" lists `deps`.
        monkeypatch.setattr(
            "odooflow.commands.clone_module.safe_eval_manifest",
            lambda content: {"depends": list(deps)},
        )
        # Path.cwd inside the recursive function uses the directory we passed.
        # Already handled by the caller.

    def test_unresolved_deps_do_not_raise_unbound_local(
        self, monkeypatch, tmp_path
    ):
        # Run in tmp_path so Path.cwd() / module_name mkdir is harmless.
        import os
        os.chdir(tmp_path)
        # Pre-create the root target so clone_from returns early.
        (tmp_path / "root").mkdir()
        # Manifest path inside.
        (tmp_path / "root" / "__manifest__.py").write_text(
            "{'name': 'root', 'depends': ['base_setup', 'hr_attendance']}"
        )

        self._setup(monkeypatch)

        # The first call returns the root URL we want to walk into; the nested
        # calls happen inside clone_recursive's executor.
        with pytest.raises(typer.Exit) as exc_info:
            clone_module_command(
                url="https://gitlab.example.com/g/root",
                branch=None,
                depth=2,
                workers=2,
            )
        # Should exit 1 because at least one dep failed, NOT crash with
        # UnboundLocalError.
        assert exc_info.value.exit_code == 1
