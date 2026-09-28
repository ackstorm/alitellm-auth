---
name: mcp-setup
description: Add this organization's MCP servers to OpenCode (globally or for one project) and sign in to them with OAuth. Use when the user wants to connect, add, enable, authenticate, re-authenticate, troubleshoot or remove an MCP server.
---

# MCP setup

Every MCP server below is reached through the organization's gateway and signs in with
OAuth. No API key, `sk-` key or bearer token ever goes into a config file: OpenCode runs
the sign-in itself the first time the server answers 401, and keeps the tokens in its
own store.

## Available servers

{{servers}}

If the server the user wants is not listed, it is not available through this gateway.
Say so and stop; do not invent a URL.

## 1. Choose the scope

Ask the user which one they want, unless they already said:

- **Global** (every project): `~/.config/opencode/opencode.json`, or `opencode.jsonc`
  if that is the file that exists.
- **This project only**: `opencode.json` (or `opencode.jsonc`) at the project root.
  It is usually committed, and that is fine: the entry holds only a URL.

## 2. Add the entry

Read the file first. Merge into the existing `mcp` object; never rewrite the file or
drop keys you did not add. Keep comments in a `.jsonc` file. If the file does not exist,
create it with `"$schema": "https://opencode.ai/config.json"`.

```json
{
  "mcp": {
    "<name>": {
      "type": "remote",
      "url": "<url from the list above>",
      "enabled": true
    }
  }
}
```

Use the server name from the list as `<name>`. Do not add `headers` or an `oauth` block:
the defaults are what make the OAuth sign-in work, and `"oauth": false` disables it.

## 3. Sign in

OpenCode and OpenWork only read the config at startup, so tell the user to restart
OpenCode (or OpenWork) after editing it. Then either:

- **In a terminal:** `opencode mcp auth <name>` opens the browser. Run it for the user
  if you have a shell and they are at this machine.
- **In the chat:** the first time a tool of that server is used, OpenCode shows a sign-in
  link. Tell the user to open it.

The sign-in can show two screens: the organization's single sign-on, then, for servers
that act on an external account, that provider's consent screen. Both are expected.

## 4. Check

`opencode mcp list` shows every server and whether it is signed in. For one server
that does not connect, `opencode mcp debug <name>` explains why.

## Troubleshooting

- **401 after signing in:** the session expired or was revoked. Run
  `opencode mcp logout <name>`, then `opencode mcp auth <name>`.
- **403 `insufficient_scope`:** the sign-in did not grant this server. Sign in again as
  above; if it persists, the user's account lacks access to that server and an
  administrator must grant it.
- **Server missing from `opencode mcp list`:** wrong file, invalid JSON, or OpenCode was
  not restarted.

## Removing a server

Delete its entry from the config file and run `opencode mcp logout <name>`.

## Rules

- Never read, print or copy `~/.local/share/opencode/mcp-auth.json`; it holds tokens.
- Never put a key or token in a config file, an environment variable or the chat.
- Change only the `mcp` entries the user asked for.
