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
opencode auth login {{platform_url}}
opencode auth login -p {{provider}}   # opencode v2: opencode auth login {{provider}}
```

The first command installs the platform's plugin (OpenCode v1 and v2); the second signs in.

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
