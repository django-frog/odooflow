# feat(0.3.0): Named server profiles with first-class CLI management

## Summary

Replaces the single-anonymous-server dict with a multi-profile model and
ships a dedicated `odooflow server` subcommand for managing staging /
qa / prod profiles. Backward-compatible: existing single-server configs
auto-migrate into `remotes.servers.default` on first write.

## New user-facing surface

```
odooflow server list            # tabular; --json hides passwords
odooflow server add <name>      # interactive wizard OR all-flags
odooflow server show [<name>]   # password masked unless --reveal-password
odooflow server use <name>      # set the default profile
odooflow server remove <name>
odooflow server test [<name>]   # TCP + SSH + SFTP probe, no upload

odooflow push --server <name>   # or -s; falls back to default, then legacy
```

`odooflow remote --server-json '<json>'` now writes into
`remotes.servers.default` and sets it as the default, instead of the
deprecated flat `remotes.server` field.

## Schema

```jsonc
// .odooflow.env.json
{
  "remotes": {
    "servers": {
      "staging": { "host": "...", "port": 22, "user": "...",
                   "directory": "...", "key_path": "...",
                   "post_push_cmd": "..." },
      "prod":    { "...": "..." }
    },
    "default_server": "staging"
  }
}
```

Legacy `remotes.server` is still read by `push`; nothing breaks.

## Why

| Pain point                                | After this PR                              |
|-------------------------------------------|--------------------------------------------|
| Only one server per project               | Named profiles with a default              |
| Servers were anonymous dicts              | Every profile has a name + a `*` marker    |
| JSON editing required for every change    | Wizard + flags, with validation            |
| Errors only surfaced during `push`        | Validated at `add` time + `server test`    |
| Git-side and server-side config mixed     | `odooflow remote` (git) vs `odooflow server` (deploy) |
| No way to swap staging ↔ prod             | `odooflow server use prod`                 |

## Validation included (rejected at save time, not at push time)

- Unknown keys → rejected.
- Missing required (`host`, `user`, `directory`) → rejected.
- `port` must be int 1–65535 (booleans rejected — `True` would
  otherwise slip through numeric range checks).
- `host` must not include a scheme (no `https://...`).
- `key_path` must exist on disk when supplied.

## Tests

- `tests/test_server_profile.py` — **31 tests** covering parsing,
  validation, sanitisation, profile selection, save/remove/set_default
  round-trips, and legacy migration.
- `tests/test_commands_server.py` — **17 tests** covering the CLI
  surface end-to-end via `CliRunner`: list (table + JSON), add
  (wizard + flags + migration + validation), show (default +
  named + password masking), use (set + unknown), remove (regular +
  default), test (no profile + TCP failure).
- `tests/test_commands_remote.py` updated to assert the new shape.
- Total: **114 passed in 1.24s.** No regressions, no tracebacks.

## Backward compatibility

- 0.1/0.2 single-server configs (`remotes.server = {...}`) keep
  working. The flat form is auto-migrated to `remotes.servers.default`
  on the first write performed by `remote --server-json` or
  `server add`.
- `odooflow push` continues to work for users who only have the
  legacy field: if `--server` is not given and no `default_server`
  is set, the legacy block is used.

## Files changed

```
 M  README.md
 M  odooflow/__init__.py                         (bump 0.2.0 -> 0.3.0)
 M  odooflow/cli.py                              (register server sub-typer)
 M  odooflow/commands/push.py                    (--server resolution, better error hints)
 M  odooflow/commands/remote.py                  (--server-json writes servers.default)
 A  odooflow/commands/server.py                 (NEW — 6 sub-commands)
 A  odooflow/utils/server_profile.py            (NEW — schema, validation, persistence)
 M  pyproject.toml                               (bump 0.2.0 -> 0.3.0)
 M  tests/test_commands_remote.py               (assert new schema)
 A  tests/test_commands_server.py               (NEW — 17 tests)
 A  tests/test_server_profile.py                (NEW — 31 tests)
```

11 files changed, 1471 insertions(+), 20 deletions(-).

## Manual verification

```bash
$ odooflow server list
NAME      HOST                PORT  USER     KEY                DEFAULT  POST-CMD
staging   staging.example.com 22    deploy   ~/.ssh/stg_rsa     *        restart odoo-staging
prod      prod.example.com    22    deploy   ~/.ssh/prod_rsa              (none)

$ odooflow server test staging
  Testing staging → deploy@staging.example.com:22

  [tcp]   reachable
  [auth]  ok
  [dir]   /opt/odoo/staging/addons exists

  [dry-run]  would execute on remote: sudo systemctl restart odoo-staging

  ✓ Connection succeeded.

$ odooflow push --server staging --remote-only --exec "sudo systemctl restart odoo-staging"
```

## Build

- `dist/odooflow_cli-0.3.0-py3-none-any.whl` rebuilt and reinstalled.

## Decisions / trade-offs (record for reviewers)

1. **Profile keys at root of `servers` dict, not a list of `{name, ...}`** —
   keeps `default_server` lookup O(1) and avoids the list-search-on-every-push
   cost.
2. **Plaintext passwords in env file** — consistent with how `access_token`
   is already stored in `~/.odooflowrc`. A `keyring` migration is a
   follow-up.
3. **`server test` does not honour `--exec`** in dry-run mode (just prints).
   If anyone wants the actual dry-run, a future `--dry-run` flag is the
   right place for it.
4. **No global `~/.odooflow_servers.toml`** — left for a follow-up PR if
   teams ask for it.
5. **Deprecation hint for legacy `remotes.server`** is silent in this PR
   to keep the diff small. A follow-up can add a `one-time` warning at
   `load_config` time.
