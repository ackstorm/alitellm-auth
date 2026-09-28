# PROVIDER_NAME + `genai-api` skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Run AFTER** both `2026-09-28-opencode-config-endpoint.md` and
> `2026-09-28-opencode-plugin-config-hook.md` have landed in the working tree: it edits
> the code they add. **Before** the release that ACH vendors.
>
> **Size note**: ~60 lines of production code + one rewritten template + test updates.
> Execute INLINE, one review at the end.

**Goal:** The product is resellable: nothing a user sees says "ackstorm" unless the deployment chooses it. One setting, `PROVIDER_NAME` (default `ai-platform`; `ackstorm` on the ACKstorm cluster), names the OpenCode provider, the plugin's data folder and the provider display name. The `mcp-setup` skill becomes the generic `genai-api` skill describing the platform.

**Architecture:** `settings.provider_name` flows to (1) the config endpoint's provider id and display name, (2) `platform.json.provider` in the plugin tarball, (3) the skill template. The plugin reads `provider` from `platform.json`/options at load and derives its id and data folder `~/.local/share/opencode/<provider>/` from it. The wire schema `ackstorm.opencode-config/1` is NOT renamed (not user-visible; agreed with ACH).

**Tech Stack:** as in the two previous plans.

## Global Constraints

- `PROVIDER_NAME`: default `ai-platform`; must match `^[a-z0-9][a-z0-9-]{0,63}$` (OpenCode provider ids are `[0-9a-z-]`). Chart value `config.providerName`.
- **Source of the value** (done 2026-09-28): Terraform `terraform-genai-blueprint-module` variable `provider_name` (`ackstorm` in its tfvars, commit `34b274e`) → secret `flux-system/terraform-genai-data` key `GENAI_PROVIDER_NAME` → gitops HelmRelease `config.providerName: ${GENAI_PROVIDER_NAME}` (apps/alitellm-auth/base/helm.yaml; the Kustomization already substitutes from that secret).
- **Release blocker**: the Terraform apply and the gitops value MUST be live before this ships. Otherwise the chart default `ai-platform` applies, every existing user's stored credential (`auth.json` key `ackstorm`) no longer matches, and they must sign in again.
- The plugin contains no product string. Its default provider id is `ai-platform` (only used if `platform.json` has none).
- Plugin data: `$XDG_DATA_HOME/opencode/<provider>/client.json`, `config.json`, `skills/<name>/SKILL.md`. Legacy `$XDG_DATA_HOME/opencode/<provider>-client.json` is read as a fallback for the DCR identity (with provider `ackstorm` that is today's `ackstorm-client.json`), so nobody re-signs in.
- Skill name `genai-api` (fixed, generic). Template placeholders `{{provider}}`, `{{console_url}}`, `{{api_url}}`, `{{mcp_servers}}`, filled from `PROVIDER_NAME`, `APP_BASE_URL`, `API_PUBLIC_URL`, `AS_SERVICES`.
- Schema string stays `ackstorm.opencode-config/1`.
- Commits only after user approval.

## File Structure

| File | Change |
|---|---|
| `src/api/app/config.py` | + `provider_name` + validator |
| `deploy/helm/alitellm-auth/values.yaml`, `templates/deployment.yaml` | `config.providerName` → env `PROVIDER_NAME` |
| `src/api/app/opencode_config.py` | provider id + display name from settings; skill import |
| `src/api/app/public.py` | `platform.json.provider` |
| `src/api/app/skills/__init__.py`, `genai-api.md` (new), `mcp-setup.md` (delete) | skill rename + rewrite |
| `clients/opencode/index.mjs`, `README.md`, `package.json` | provider from platform.json, per-provider data folder |
| tests | `test_config.py`, `test_skills.py`, `test_opencode_config.py`, `test_public.py`, both plugin test files |
| `CHANGELOG.md`, `CLAUDE.md`, spec | entries |

---

### Task 1: Server — `PROVIDER_NAME` and the `genai-api` skill

**Interfaces:**
- Produces: `settings.provider_name: str`; `app.skills.GENAI_API = "genai-api"`; `app.skills.genai_api_body(settings) -> str` (replaces `MCP_SETUP` / `mcp_setup_body`); `platform.json` gains `"provider"`.

- [ ] **Step 1: Failing tests**

`tests/test_config.py` (reuse that file's settings factory; the kwargs below are the override):

```python
def test_provider_name_defaults_to_a_neutral_id():
    assert make_settings().provider_name == "ai-platform"


@pytest.mark.parametrize("bad", ["ACKstorm", "a b", "-x", "", "x" * 65, "a/b"])
def test_provider_name_must_be_an_opencode_provider_id(bad):
    with pytest.raises(ValidationError):
        make_settings(provider_name=bad)
```

(Use the factory name and `ValidationError` import that `test_config.py` already has.)

Replace `tests/test_skills.py` entirely:

```python
# SPDX-License-Identifier: Apache-2.0
"""Tests for the SKILL.md templates served to OpenCode clients."""

from app.skills import GENAI_API, genai_api_body
from tests.as_defaults import AS_TEST_DEFAULTS

SERVICES = (
    '{"mcp-google-drive": {"store": "google-drive", "broker": "https://b.test/g"},'
    ' "mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://b.test/a"}}'
)


def _settings(**overrides):
    from app.config import Settings

    base = dict(
        app_base_url="https://console.example.com/",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.example.com/",
        as_services=SERVICES,
        **AS_TEST_DEFAULTS,
    )
    base.update(overrides)
    return Settings(**base)


def test_genai_api_is_filled_from_settings():
    text = genai_api_body(_settings(provider_name="acme"))
    assert GENAI_API == "genai-api"
    assert text.startswith("---\nname: genai-api\n")
    assert "{{" not in text and "}}" not in text
    assert "https://console.example.com/ui/" in text
    assert "https://api.example.com/v1" in text
    assert "opencode auth login -p acme" in text
    assert "opencode plugin https://api.example.com/clients/opencode/plugin -g" in text
    assert (
        "- `mcp-aws-eks-ro`: `https://api.example.com/mcp/mcp-aws-eks-ro`\n"
        "- `mcp-google-drive`: `https://api.example.com/mcp/mcp-google-drive`"
    ) in text


def test_genai_api_is_brand_neutral_by_default():
    assert "ackstorm" not in genai_api_body(_settings()).lower()


def test_genai_api_without_services():
    text = genai_api_body(_settings(as_services=""))
    assert "No per-server OAuth endpoints are configured on this platform." in text
```

`tests/test_opencode_config.py` (from the endpoint plan): the provider key is now the setting.
- Replace every `["ackstorm"]` lookup in helpers/tests with `[settings.provider_name]` (the `_models(body)` helper becomes `_models(body, provider="ai-platform")` using `body["config"]["provider"][provider]`).
- Add:

```python
def test_provider_id_and_name_follow_provider_name(groups, admin):
    settings = _settings(provider_name="acme")
    client = TestClient(create_app(settings=settings), raise_server_exceptions=False)
    provider = _get(client, _token(settings)).json()["config"]["provider"]
    assert list(provider) == ["acme"]
    assert provider["acme"]["name"] == "acme"
    body = _get(client, _token(settings)).json()
    assert [s["name"] for s in body["skills"]] == ["genai-api"]
```

- Existing `mcp-setup` assertions in that file become `genai-api` (`startswith("---\nname: genai-api\n")`).

`tests/test_public.py` (from the endpoint plan): the expected `platform.json` gains `"provider": "ai-platform"`; add a case with `provider_name="acme"` → `"provider": "acme"`. `_plugin_tgz` calls in tests take the extra argument (see Step 3).

- [ ] **Step 2: Run, expect FAIL** — `cd src/api && .venv/bin/pytest tests/test_config.py tests/test_skills.py tests/test_opencode_config.py tests/test_public.py -q`.

- [ ] **Step 3: Implement**

`app/config.py` — next to the other presentation settings (`brand`, `brand_short`):

```python
    # The OpenCode provider id AND every user-visible name derived from it:
    # `opencode auth login -p <provider_name>`, the provider shown in OpenCode,
    # the plugin's data folder, the genai-api skill. Neutral by default so a
    # resold deployment names itself. Changing it on a live deployment signs
    # every OpenCode user out (their stored credential is keyed by it).
    provider_name: str = "ai-platform"
```

and a validator (match the file's existing `field_validator` style/imports):

```python
    @field_validator("provider_name")
    @classmethod
    def _provider_name_is_an_opencode_id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", v):
            raise ValueError("PROVIDER_NAME must be lowercase letters, digits and '-' (max 64)")
        return v
```

(`import re` if not present.)

`deploy/helm/alitellm-auth/values.yaml` under `config:` (after `litellmDefaultTeam`):

```yaml
  # User-visible name of this platform in OpenCode and the genai-api skill:
  # `opencode auth login -p <providerName>`. Lowercase, digits, '-'. Neutral
  # default; the ACKstorm cluster sets "ackstorm" in gitops. Changing it on a
  # live deployment signs every OpenCode user out.
  providerName: "ai-platform"
```

`templates/deployment.yaml`, next to `LITELLM_DEFAULT_TEAM`:

```yaml
            - name: PROVIDER_NAME
              value: {{ .Values.config.providerName | quote }}
```

`app/opencode_config.py`:
- Delete `OPENCODE_PROVIDER_ID` and its comment.
- `_provider(settings, models)` returns `{settings.provider_name: {"name": settings.provider_name, "npm": …, "options": …, "models": models}}`.
- Import/usage: `from app.skills import GENAI_API, genai_api_body`; `_skills()` uses them.

`app/public.py`: `_plugin_tgz(api_public_url: str, provider_name: str)`; the doc becomes

```python
    doc = json.dumps(
        {
            "api": f"{base}/v1",
            "platform": f"{parts.scheme}://{parts.netloc}",
            "provider": provider_name,
        },
        sort_keys=True,
    ).encode()
```

and the route calls `_plugin_tgz(settings.api_public_url, settings.provider_name)`. Extend the docstring: "`provider`: the OpenCode provider id (PROVIDER_NAME)".

`app/skills/__init__.py` — replace the body after the module docstring (update the docstring's "mcp-setup" mentions to "genai-api"):

```python
from __future__ import annotations

from pathlib import Path

from app.config import Settings

GENAI_API = "genai-api"
_TEMPLATE = (Path(__file__).parent / f"{GENAI_API}.md").read_text()


def genai_api_body(settings: Settings) -> str:
    """SKILL.md describing this platform, filled from Settings.

    Brand-neutral by construction: every name comes from PROVIDER_NAME and the
    deployment's URLs. The per-server OAuth MCP list is AS_SERVICES (the services
    a front-door token can carry as a scope); no per-user filtering here, a server
    the user may not use answers 403, which the skill explains.
    """
    api = settings.api_public_url.rstrip("/")
    names = sorted(settings.services)
    if names and api:
        servers = "\n".join(f"- `{name}`: `{api}/mcp/{name}`" for name in names)
    else:
        servers = "No per-server OAuth endpoints are configured on this platform."
    values = {
        "provider": settings.provider_name,
        "console_url": f"{settings.app_base_url.rstrip('/')}/ui/",
        "api_url": api,
        "mcp_servers": servers,
    }
    text = _TEMPLATE
    for key, value in values.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text
```

Delete `app/skills/mcp-setup.md`. Create `app/skills/genai-api.md`:

````markdown
---
name: genai-api
description: How to use this organization's GenAI platform ({{provider}}) - the web console, API keys, available models, MCP servers and how to connect tools to it (OpenCode first). Use when the user asks how to get, rotate or delete an API key, which models or MCP servers exist, how to connect a tool or an MCP server to the platform, or why a request to it fails (401, 403, 404, 429, budget).
---

# The {{provider}} GenAI platform

Everything goes through one gateway, and one web console manages it. Both use the
organization's single sign-on.

- **Console:** {{console_url}} - tabs Keys, Stats, Models, MCP, A2A, How-To.
- **Gateway (OpenAI-compatible):** `{{api_url}}/v1`

Never invent a URL, model name or server name: use the values in this file or what
the console shows.

## Access

- **OpenCode** signs in with single sign-on through the `{{provider}}` plugin. It needs
  no API key (see "OpenCode" below).
- **Any other tool or script** needs an API key (`sk-...`). The user creates it in the
  console, Keys tab ({{console_url}}). It is shown once: tell the user to store it in an
  environment variable or the tool's secret store, and to delete it in the same tab
  when it is no longer needed.
- Never ask the user to paste a key into the chat. Never put one in a file that could
  be committed.

## Models

- The console's Models tab lists the models this account can use, with context size,
  price and capabilities.
- From a terminal, with the key in `$API_KEY`:
  `curl -s {{api_url}}/v1/models -H "Authorization: Bearer $API_KEY"`
- A model that is not listed is not enabled for this account. An administrator grants
  access; do not try other names.

## MCP servers

Two ways in:

1. **One server at a time, with single sign-on** (MCP clients that support OAuth, such as
   OpenCode):

{{mcp_servers}}

   The first use opens the organization's sign-in and, for servers that act on an
   external account, that provider's consent screen. Both are expected.

2. **All of the account's servers behind one endpoint, with an API key** (any MCP client):
   `{{api_url}}/mcp` with the header `x-litellm-api-key: Bearer <key>`. The optional
   header `x-mcp-servers: <name>,<name>` narrows it. The console's MCP tab lists the
   servers this account can use.

## OpenCode

One-time setup, in a terminal. The agent cannot do this for the user: until OpenCode
is signed in there is no model to run it.

```
opencode plugin {{api_url}}/clients/opencode/plugin -g
opencode auth login -p {{provider}}
```

Then restart OpenCode. The platform's models appear under the provider `{{provider}}`,
its MCP servers appear **disabled**, and this skill is available. Every start picks up
the platform's current list; the user's own config always wins over it.

- **Enable an MCP server:** in `~/.config/opencode/opencode.json` (all projects) or the
  project's `opencode.json`, set `"enabled": true` for that server under `mcp`. Read the
  file first, change only that key, keep comments in a `.jsonc` file. Restart OpenCode,
  then run `opencode mcp auth <name>`.
- **Check:** `opencode mcp list` shows each server and whether it is signed in;
  `opencode mcp debug <name>` explains a server that does not connect.
- **Do not** set `OPENCODE_MODELS_URL` or export an API key for this provider: the plugin
  handles both, and an exported key would override the sign-in.

## Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| 401 on every request | The key is missing, wrong or deleted; in OpenCode, the sign-in expired | New key in the Keys tab; in OpenCode `opencode auth login -p {{provider}}` |
| 404 model not found | The model is not enabled for this account, or the name is wrong | Check the Models tab |
| 429 | Rate limit | Retry later, with backoff |
| Budget or spend limit exceeded | The account reached its spend limit | The Stats tab shows spend and limit; an administrator can raise it |
| MCP 401 after signing in | The MCP session expired or was revoked | `opencode mcp logout <name>`, then `opencode mcp auth <name>` |
| MCP 403 `insufficient_scope` | The sign-in did not grant this server | Sign out and in again as above |
| MCP 403 from the gateway, or the sign-in loops | The account lacks access to that server | An administrator grants it (access group) |
| MCP server missing from `opencode mcp list` | Wrong file, invalid JSON, or OpenCode not restarted | Fix the file, restart |

## Rules

- Never read, print or copy keys or tokens, including `~/.local/share/opencode/auth.json`
  and `~/.local/share/opencode/mcp-auth.json`.
- Change only the configuration the user asked for.
````

- [ ] **Step 4: Run, expect PASS** — same command as Step 2, then the full suite:
`.venv/bin/pytest tests/ -q > /tmp/pt.log 2>&1; echo EXIT=$?; tail -3 /tmp/pt.log`.

---

### Task 2: Plugin — provider from `platform.json`, per-provider data folder

**Interfaces:**
- Consumes: `platform.json.provider` (Task 1) or options `{provider}`.
- Produces: module-level `PROVIDER` set at load; `paths()` → `{client, legacyClient, cache, skills}`.

- [ ] **Step 1: Failing tests**

`test/opencode-config-hook.test.mjs`:
- `OPTIONS` gains `provider: "acme"`; `DATA`-derived paths become
  `const HOME = \`${DATA}/acme\``, `CACHE = \`${HOME}/config.json\``, `SKILLS = \`${HOME}/skills\``.
- `signIn()` writes `auth.json` as `{ acme: {…} }` and the DCR file to `${HOME}/client.json` (mkdir `HOME`).
- Add:

```js
test("the provider id comes from the backend, and the legacy client file still works", async () => {
  mkdirSync(DATA, { recursive: true })
  writeFileSync(`${DATA}/auth.json`, JSON.stringify({ acme: { type: "oauth", access: jwt("alice@example.com"), refresh: "r1", expires: 0 } }))
  writeFileSync(`${DATA}/acme-client.json`, JSON.stringify({ issuer: ISSUER, client_id: "c1" })) // pre-folder layout
  const client = { auth: { set: async ({ path, body }) => { saved.push({ id: path.id, body }) } } }
  saved = []
  const hooks = await SsoAuth({ client }, OPTIONS)
  assert.equal(hooks.auth.provider, "acme")
  await hooks.config({})
  assert.equal(saved[0].id, "acme")
})
```

`test/opencode-auth.test.mjs`: pass `provider: "acme"` in the options object of every `SsoAuth(...)` call and assert once `hooks.auth.provider === "acme"`. The legacy test (no options) asserts `hooks.auth.provider === "ai-platform"`. Adjust any path to the DCR file to `${XDG_DATA_HOME}/opencode/acme/client.json`.

- [ ] **Step 2: Run, expect FAIL** — `node --test test/opencode-auth.test.mjs test/opencode-config-hook.test.mjs`.

- [ ] **Step 3: Implement** in `clients/opencode/index.mjs`

Replace `const PROVIDER = "ackstorm"`, `CLIENT_FILE`, `CONFIG_CACHE`, `SKILLS_DIR` with:

```js
// The provider id and data folder come from the backend (platform.json
// `provider`, or plugin options). ponytail: one backend per opencode process, so
// module-level; set once in SsoAuth before anything reads it.
let PROVIDER = "ai-platform"
const PROVIDER_ID = /^[a-z0-9][a-z0-9-]{0,63}$/
const paths = () => ({
  client: `${DATA}/${PROVIDER}/client.json`, // DCR result; opencode has no plugin KV
  legacyClient: `${DATA}/${PROVIDER}-client.json`, // layout before the per-provider folder
  cache: `${DATA}/${PROVIDER}/config.json`,
  skills: `${DATA}/${PROVIDER}/skills`,
})
```

- `savedClientId(issuer)`: try `paths().client`, then `paths().legacyClient`:

```js
async function savedClientId(issuer) {
  for (const file of [paths().client, paths().legacyClient]) {
    try {
      const saved = JSON.parse(await readFile(file, "utf8"))
      if (saved.issuer === issuer) return saved.client_id
    } catch {}
  }
  return null
}
```

- `clientId()`: write to `paths().client` after `mkdir(\`${DATA}/${PROVIDER}\`, { recursive: true, mode: 0o700 })`.
- Every `CONFIG_CACHE` → `paths().cache`, `SKILLS_DIR` → `paths().skills`; `writePrivate` creates `\`${DATA}/${PROVIDER}\`` (0700) instead of `DATA`.
- `SsoAuth` start:

```js
export async function SsoAuth({ client }, options = {}) {
  const { provider } = await backend(options)
  if (PROVIDER_ID.test(provider ?? "")) PROVIDER = provider
```

- Header comment: `opencode auth login -p ackstorm` → `opencode auth login -p <provider>`; the last line "PROVIDER is that config's provider id." → "The provider id comes from platform.json (`provider`)."

`clients/opencode/README.md`:
- Install block: `opencode auth login -p <provider>` (the value in `platform.json`).
- `platform.json` table: add row `| provider | The OpenCode provider id (the deployment's PROVIDER_NAME): \`opencode auth login -p <provider>\`, and the name of the plugin's data folder. |`
- "Files it writes" paths: `<provider>/client.json`, `<provider>/config.json`, `<provider>/skills/<name>/SKILL.md` under `$XDG_DATA_HOME/opencode`.

`clients/opencode/package.json`: `"version": "0.4.0"` (or keep 0.3.0 if 0.3.0 was never released — check `git tag`/CHANGELOG; one bump per release).

- [ ] **Step 4: Run, expect PASS** — same command; `node --check clients/opencode/index.mjs`.

---

### Task 3: Docs, gates, review

- [ ] `CHANGELOG.md` `[unreleased]`: replace the `mcp-setup` entry with:

```markdown
- **`PROVIDER_NAME`** (chart `config.providerName`, default `ai-platform`): the
  user-visible platform name, used as the OpenCode provider id
  (`opencode auth login -p <name>`), the provider shown in OpenCode, the
  plugin's data folder (`~/.local/share/opencode/<name>/`) and in the skill.
  **Set it to the id your users already use** (the ACKstorm cluster: `ackstorm`)
  or every OpenCode user must sign in again.
- **`genai-api` skill** (replaces `mcp-setup`): a brand-neutral guide to the
  platform delivered to OpenCode: console, API keys, models, MCP servers
  (per-server OAuth URLs and the key-based `/mcp` endpoint), OpenCode setup
  and troubleshooting. Filled from `PROVIDER_NAME`, `APP_BASE_URL`,
  `API_PUBLIC_URL` and `AS_SERVICES`.
```

- [ ] `CLAUDE.md` Environment Variables table: row `| PROVIDER_NAME | deployment env (opt) | Default ai-platform. User-visible platform name: OpenCode provider id, plugin data folder, genai-api skill. Changing it on a live deployment signs every OpenCode user out. Helm: config.providerName |`.
- [ ] Spec `docs/superpowers/specs/2026-09-27-opencode-client-config-and-den.md`, Rev 4: add
  `- **R4-9 PROVIDER_NAME** (2026-09-28): the provider id is not "ackstorm" by contract; it is each deployment's PROVIDER_NAME (default "ai-platform"), carried to the plugin as platform.json.provider. The skill is "genai-api". The schema string is unchanged.`
- [ ] **Gates**: full pytest (EXIT=0), `ruff@0.8.4 check` + `format --check`, both `node --test` files, `helm template deploy/helm/alitellm-auth | grep -A1 PROVIDER_NAME`.
- [ ] **Neutrality check**: `git grep -in ackstorm -- clients/opencode src/api/app/skills src/api/app/opencode_config.py src/api/app/public.py` returns only the schema string `ackstorm.opencode-config/1`.
- [ ] One review, then commit after user approval.

## Release checklist addition

Before tagging: `kubectl -n flux-system get secret terraform-genai-data -o jsonpath='{.data.GENAI_PROVIDER_NAME}' | base64 -d` prints `ackstorm`, and gitops `apps/alitellm-auth/base/helm.yaml` has `providerName: ${GENAI_PROVIDER_NAME}` under `config:`.
Verify after deploy: `curl -s https://api.ackstorm.ai/clients/opencode/plugin | tar -xzO package/platform.json`
shows `"provider": "ackstorm"`.

## Out of scope

- Existing brand strings outside these files (`HowTo.tsx` examples, chart defaults,
  `clients/ackstorm-token`, `BrandLockup.tsx`, `Chart.yaml`): separate cleanup.
- Skill sections for other tools (Claude Code, Codex, …): added later, same template.
