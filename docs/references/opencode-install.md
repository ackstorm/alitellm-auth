# OpenCode install: one URL, engines v1 and v2

Verified 2026-09-29 on opencode v1 (1.18.33) and v2 (2.0.18) against `docker-compose.opencode-mock.yml`.

## Flow

`opencode auth login https://<platform-host>` fetches `GET /.well-known/opencode`
(`src/api/app/public.py::opencode_wellknown`), installs the plugin it names, then
`opencode auth login -p <provider>` (v2: `opencode auth login <provider>`) runs the plugin's SSO.

## Manifest

```json
{"auth": {"command": ["echo", "ok"], "env": ""},
 "config": {"plugin": [["git+https://github.com/ackstorm/opencode-oidc-provider.git#v0.4.0",
                        {"api": "<origin>/v1", "platform": "<origin>", "provider": "ai-platform"}]]}}
```

- `auth` is mandatory (v2 `WellKnown.add` fails without it); `env` MUST be a string. The plugin ignores the credential the command yields. `echo ok` because OpenCode spawns it shell-less via cross-spawn: `/bin/echo` on Linux/macOS, `cmd.exe /c` fallback on Windows; `opencode` is often not on PATH.
- Public data only: never a token, key or user data.
- `api`/`platform` in plugin options must be bare origins (`api` ends `/v1`).
- Plugin spec: `OPENCODE_PLUGIN_SPEC` (Helm `config.opencodePluginSpec`), a git spec at the repo root pinned to a tag.

## Engine matrix (install source)

| Source | v1 | v2 |
|---|---|---|
| tarball URL (removed from this service) | works | no |
| `::path:` subdir git spec | ignored | works |
| repo-root git spec / well-known | works | works |

This service serves no tarball: the only install is `/.well-known/opencode` → git spec.

## Gotchas

- Origin down at startup → opencode starts without the plugin (no error).
- v2 managed-service port collision shows as `UnexpectedStatus: 500`.
- opencode needs a TTY: never run login/run with stdout redirected (hangs).
- Platform URL (ingress.host) and API URL both work: gitops `httproute-api.yaml` routes `/.well-known/opencode` on the API host here. Without that rule, v1 crashes on the 404 with `undefined is not an object (evaluating 'N.auth.command')`.

## Only the platform's provider

The manifest's `config` also carries `"enabled_providers": ["<provider>"]`. v1 reads it as is;
v2 turns it into `provider.use` policies (deny `*`, allow the provider; `normalize.ts:384-402`).
Verified 2026-09-29: v1 `opencode models` and the v2 TUI `/models` list only the platform's
provider. A default, not a lock: the user's own `opencode.json` overrides it. Note: on v2,
`opencode models` (CLI) prints nothing (it does not load plugins); check the TUI picker.

## Default / small model

`DEFAULT_MODEL` / `DEFAULT_SMALL_MODEL` (Helm `config.defaultModel` /
`defaultSmallModel`; bare names, unset = none). Served as `model` / `small_model`
(`"<provider>/<name>"`) in the per-user `/clients/opencode/config`, NOT in the public well-known
manifest: only there is the user's own model list known. Omitted when the user's key does not see
the model (OpenCode then picks the first one). The user's own `opencode.json` still wins.
