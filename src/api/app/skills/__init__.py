# SPDX-License-Identifier: Apache-2.0
"""Skills served to OpenCode clients.

Each skill is a SKILL.md template next to this module. Templates are rendered
per request from Settings; nothing here reads user data. Delivered by
`GET /clients/opencode/config` (docs/superpowers/specs/2026-09-27-opencode-client-config-and-den.md
§4.2.2), not by the OpenWork Den.
"""

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
        "platform_url": settings.app_base_url.rstrip("/"),
        "api_url": api,
        "mcp_servers": servers,
    }
    text = _TEMPLATE
    for key, value in values.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text
