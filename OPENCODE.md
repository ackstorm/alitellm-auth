# OpenCode integration (engines v1 and v2)

How OpenCode users sign in to the platform, and what an operator has to set up. Both
OpenCode engines are supported with the same plugin and the same platform URL:

| Engine | Tested versions |
|---|---|
| v1 | 1.18.x |
| v2 | 2.0.x |

## Which engine on which machine

**One engine per machine** (decided 2026-09-29):

| Machine | Install | Why |
|---|---|---|
| **Personal machines** (with OpenWork) | OpenCode **v1 only**. Keep OpenWork's "Experimental engine" (v2) **off**. | OpenWork's v1 engine loads the user's plugins, so our plugin works there. Its v2 engine runs a private config dir, loads only OpenWork's own plugins, and its connect dialog cannot start a v2 OAuth login: no platform models. |
| **Remote / external machines** (servers, VMs, dev containers; no OpenWork) | OpenCode **v2** | The current engine; plugin, models, MCP and skills all work. |

Never both engines on one machine: they share `~/.local/share/opencode/opencode.db`, and
once v2 has migrated it, v1 fails with `Database is not empty and has no session table`.
To run both anyway (testing only), give one of them its own `XDG_DATA_HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `XDG_STATE_HOME`. Don't unpack the binary as
`/tmp/opencode`: it collides with OpenCode's temp dir (`EEXIST: mkdir '/tmp/opencode'`).

Throughout this page, `https://platform.example.com` is the platform (console) URL and
`ai-platform` is the provider id (the deployment's `PROVIDER_NAME`). Use your own values.

## What you get

After signing in, every OpenCode start:

- Adds the platform provider with the models your key can use (`ai-platform/<model>`).
- Registers every MCP server your key can reach, **disabled** (`api.<domain>/mcp/<name>`).
  Turn one on and OpenCode signs in to it through the platform's OAuth.
- Adds the platform's skills.
- Hides every other provider in the model picker (a default; see [Showing other providers](#showing-other-providers)).
- Refreshes the token by itself; you sign in once.

Your own `opencode.json` always wins over what the platform sends.

## Install and sign in

Two commands. Only the second one differs between engines.

```bash
# 1. Install and configure the plugin (same on v1 and v2)
opencode auth login https://platform.example.com

# 2. Sign in with SSO
opencode auth login -p ai-platform     # v1
opencode auth login ai-platform        # v2
```

Step 2 offers two methods:

- **SSO (browser)**: opens the browser, you sign in, done.
- **SSO (device code)**: for remote or headless hosts. OpenCode prints a `XXXX-XXXX` code
  and a URL. Open the URL in any browser, confirm the code and sign in. The terminal
  finishes on its own.

Restart OpenCode after signing in, and whenever the platform changes your models, MCP
servers or skills: the config is loaded at start.

### Check it worked

| | v1 | v2 |
|---|---|---|
| Logins | `opencode auth list` | `opencode auth list` |
| Models | `opencode models` | TUI → `/models` |

On v2, the `opencode models` CLI prints nothing: it does not load plugins. Use the model
picker in the TUI.

## What step 1 does

`opencode auth login https://platform.example.com` fetches
`https://platform.example.com/.well-known/opencode`, a public manifest:

```json
{
  "auth": {"command": ["echo", "ok"], "env": ""},
  "config": {
    "plugin": [["git+https://github.com/ackstorm/opencode-oidc-provider.git#v0.4.4",
                {"api": "https://api.example.com/v1",
                 "platform": "https://api.example.com",
                 "provider": "ai-platform"}]],
    "enabled_providers": ["ai-platform"]
  }
}
```

OpenCode saves the origin and merges that `config` block on every start. So a new plugin
version or option reaches users with no action on their side beyond a restart.

The manifest's `auth` entry is required by OpenCode but not used: the real tokens come from
step 2 and are stored under the provider id (`ai-platform`), not under the origin.

## Logins: two entries, log out in order

After install and sign-in, OpenCode holds two separate entries:

| Entry | What it is |
|---|---|
| `platform.example.com` | The saved origin. It is what loads the plugin. |
| `ai-platform` | Your SSO tokens. |

The plugin, and so the `ai-platform` entry, only exists while the origin is saved. To log
out cleanly, **tokens first, then the origin**:

```bash
opencode auth logout ai-platform       # v2; on v1: opencode auth logout, then pick it
opencode auth logout platform.example.com
```

The other way round, `ai-platform` fails with `Integration not found`: the tokens stay
stored but nothing can reach them until the origin is added again.

## Engine differences

| | v1 | v2 |
|---|---|---|
| Sign-in command | `opencode auth login -p ai-platform` | `opencode auth login ai-platform` |
| Plugin entry point | `default.server` | `default.setup` |
| `enabled_providers` | read as is | turned into `provider.use` policies (deny `*`, allow ours) |
| List models from the CLI | `opencode models` | TUI `/models` only |
| Background process | none | managed service on port `49374` |
| Plugin install sources | npm, git (repo root), tarball URL | npm, git (repo root or `::path:`), local dir |

One file in the plugin repo serves both engines, and it lives at the repo root because
v1 ignores git `::path:` subdirectories.

## Showing other providers

`enabled_providers` is a default. To also see your own providers, set it in your
`~/.config/opencode/opencode.json`, which overrides the manifest:

```json
{ "enabled_providers": ["ai-platform", "anthropic"] }
```

## Manual install (no manifest)

For a platform that doesn't serve `/.well-known/opencode`, or to pin a different plugin
version, put the plugin in `~/.config/opencode/opencode.json` yourself, then run step 2:

```json
{
  "plugin": [
    ["git+https://github.com/ackstorm/opencode-oidc-provider.git#v0.4.4",
     {"api": "https://api.example.com/v1",
      "platform": "https://api.example.com",
      "provider": "ai-platform"}]
  ]
}
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Integration not found` on any `auth login`/`logout` (v2) | A saved origin that no longer answers (e.g. an old `http://127.0.0.1:…`). v2 loads every saved origin and one dead origin breaks them all. | Stop OpenCode (including `opencode serve --service`), then drop the dead origin from `kv['wellknown:sources']` in `~/.local/share/opencode/opencode.db`. `opencode --standalone` bypasses the service to test. Don't delete `opencode.db`: it holds all sessions and logins. |
| `Integration not found: ai-platform` after logging out the origin | Logged out in the wrong order. | `opencode auth login https://platform.example.com`, then log out the tokens first. |
| `UnexpectedStatus: 500` (v2) | A stale managed service on port `49374`, or a wrong `api` option (e.g. missing port). | Stop the old `opencode serve --service`; check the options in the manifest. |
| Signed in, but no platform models | The platform was unreachable at start (OpenCode starts without the plugin, silently), or the config fetch was refused. | Check `curl https://platform.example.com/.well-known/opencode`, restart OpenCode, look at the TUI `/models`. |
| Two platforms, models from only one | Both deployments use the same provider id, so they share one token slot and overwrite each other. | Give each deployment its own `PROVIDER_NAME`. |
| v2 on a headless host exits instead of printing the login URL | No browser opener. | Use device code, or put a stub `xdg-open` on `PATH`: `printf '#!/bin/sh\necho "$1"\n'`. |
| `auth login` hangs | OpenCode needs a TTY. | Don't redirect or pipe its output. |

## Operator setup

| Setting | Helm value | Purpose |
|---|---|---|
| `API_PUBLIC_URL` | `config.apiPublicUrl` | Required: without it `/.well-known/opencode` is 404. Used for the plugin's `api` and `platform` options. |
| `PROVIDER_NAME` | `config.providerName` | Provider id users type in step 2, model prefix, and the only entry in `enabled_providers`. Unique per deployment. Changing it signs out every OpenCode user. |
| `OPENCODE_PLUGIN_SPEC` | `config.opencodePluginSpec` | Plugin to install. Pin a tag; bump it to roll out a new plugin. |

- Users can type the **platform** or the **API** URL: the gitops `httproute-api.yaml` routes
  `/.well-known/opencode` on the API host to this service too (same body). Without that
  rule the API host answers 404 and opencode v1 crashes with
  `undefined is not an object (evaluating 'N.auth.command')`.
- The manifest is public data only: never a token, key or user data.
- Per-user config comes from `GET /clients/opencode/config` (schema
  `ackstorm.opencode-config/1`), authenticated with the user's front-door token.

Local end-to-end test against a mock backend: `docker/opencode-mock/README.md`.
Implementation notes: [docs/references/opencode-install.md](docs/references/opencode-install.md).
Plugin source: [opencode-oidc-provider](https://github.com/ackstorm/opencode-oidc-provider).
