# SPDX-License-Identifier: Apache-2.0
"""Skills served to OpenCode clients.

Each skill is a SKILL.md template next to this module. Templates are rendered
per request from Settings; nothing here reads user data. Delivered by
`GET /api/opencode/config` (docs/superpowers/specs/2026-09-27-opencode-client-config-and-den.md
§4.2.2), not by the OpenWork Den.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings

MCP_SETUP = "mcp-setup"
_TEMPLATE = (Path(__file__).parent / f"{MCP_SETUP}.md").read_text()


def mcp_setup_body(settings: Settings) -> str:
    """SKILL.md for mcp-setup with the gateway's OAuth MCP servers filled in.

    The list is AS_SERVICES: exactly the services a front-door token can carry as
    a scope, so every entry is one OpenCode can sign in to. No per-user filtering
    here; a server the user may not use answers 403 insufficient_scope, which the
    skill explains.
    """
    base = settings.api_public_url.rstrip("/")
    names = sorted(settings.services)
    if names and base:
        servers = "\n".join(f"- `{name}`: `{base}/mcp/{name}`" for name in names)
    else:
        servers = "None are configured on this gateway yet."
    return _TEMPLATE.replace("{{servers}}", servers)
