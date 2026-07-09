# chore(0.3.1): Post-merge version bump

## Summary

Bumps the version to **0.3.1** on top of `main` (which is at the merged
state of all 0.3.0 work: named server profiles, structured error UX,
and the interactive `odooflow server connect` shell).

The double-merge of `release/0.3.0` (PR #3 + PR #4) has been collapsed
in the linear history; this is a single, additive bump so a fresh
`pip install odooflow-cli` against PyPI ships the full feature set.

## What changed since the last published artifact

| Area                | What it does                                                                              |
|---------------------|--------------------------------------------------------------------------------------------|
| `pyproject.toml`    | `version = "0.3.0"` → `0.3.1`                                                             |
| `odooflow/__init__.py` | `__version__ = "0.3.0"` → `0.3.1`                                                      |
| Branches            | `release/0.3.0`, `release/0.2.1`, `release/0.2.0` deleted (local + remote) — all merged.  |
| `dist/`             | `odooflow_cli-0.3.1-py3-none-any.whl` + `odooflow_cli-0.3.1.tar.gz` regenerated.           |

The 0.3.0 feature surface is unchanged from the last successful
merge. **All 147 tests pass** on `main`; `twine check` reports
`PASSED` for both the wheel and the sdist.

## Why a patch bump (not 0.4.0)

Per SemVer:

- The named-profile schema, the `connect` subcommand, and the
  structured error path are all already on `main`. The double-merge
  only changed the commit graph, not the artifact.
- The version is bumped to make a *fresh* PyPI release
  (`pip install odooflow-cli==0.3.1`) reflect the post-merge state
  without re-narrating the entire 0.3.0 changelog.

If you would rather ship as 0.3.0 (and only adjust the artifact
without bumping the version) say so; in that case the diff is empty
and no release is needed.

## Files changed

```
 M  odooflow/__init__.py
 M  pyproject.toml
```

plus regenerated build artifacts (not committed; lives in `dist/`).

## Verification

```bash
$ python -m build
Successfully built odooflow_cli-0.3.1.tar.gz and odooflow_cli-0.3.1-py3-none-any.whl

$ python -m twine check dist/*
Checking dist/odooflow_cli-0.3.1-py3-none-any.whl: PASSED
Checking dist/odooflow_cli-0.3.1.tar.gz:       PASSED

$ python -m pytest -q
============================= 147 passed in 1.99s ==============================
```

## What you can do next (commands, ready to run)

```bash
# Push the version bump to origin/main.
git push origin main

# Tag the release.
git tag -a v0.3.1 -m "Release 0.3.1"
git push origin v0.3.1

# Upload to PyPI (TestPyPI first, then production).
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-…your-token…
python -m twine upload dist/*
```

## Decisions / trade-offs

1. **`0.3.1` over `0.3.0` re-publish.** A re-publish of 0.3.0 is
   permissible on PyPI but it requires that the *artifact* changes;
   here the only delta is the commit graph on `main`, so a patch
   bump is the honest signal. If you want to re-publish the same
   `0.3.0` artifact with the new build, that's a one-line revert.
2. **Branch hygiene.** Deleting `release/0.3.0` (and 0.2.x) makes
   the future flow cleaner: every `release/X.Y` branch lives only
   while the PR is open. To recreate it on demand, branch from
   `v0.3.1` next time.
3. **Wheel and sdist are *not* committed.** They live in `dist/`
   locally and are uploaded to PyPI as part of the release; the
   repo itself only contains the source. `.gitignore` already
   excludes `dist/`, `build/`, and `*.egg-info/`.
