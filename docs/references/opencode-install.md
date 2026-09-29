# OpenCode install: one URL, engines v1 and v2

Verified 2026-09-29 on opencode v1 (1.18.33) and v2 (2.0.18) against `docker-compose.opencode-mock.yml`.

## Flow

`opencode auth login https://<platform-host>` fetches `GET /.well-known/opencode`
(`src/api/app/public.py::opencode_wellknown`), installs the plugin it names, then
`opencode auth login -p <provider>` (v2: `opencode auth login <provider>`) runs the plugin's SSO.

## Manifest

```json
{"auth": {"command": ["opencode", "--version"], "env": ""},
 "config": {"plugin": [["git+https://github.com/ackstorm/opencode-oidc-provider.git#v0.4.0",
                        {"api": "<origin>/v1", "platform": "<origin>", "provider": "ai-platform"}]]}}
```

- `auth` is mandatory (v2 `WellKnown.add` fails without it); `env` MUST be a string. The plugin ignores the credential the command yields.
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
- Users type the PLATFORM URL (ingress.host). Serving it on the API host needs a gitops HTTPRoute rule for `/.well-known/opencode`.
