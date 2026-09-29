# SPDX-License-Identifier: Apache-2.0
"""Standalone mock of an ackstorm.opencode-config/1 backend: fake OAuth AS
(RFC 9728/8414 discovery, DCR, PKCE browser flow, RFC 8628 device flow) plus
/clients/opencode/config and an OpenAI-compatible /v1/chat/completions.

Zero dependencies (stdlib only) so it runs anywhere Python 3 does. Used to
validate the clients/opencode plugin (v1 and v2) end to end, including
OpenWork, without needing a real ackstorm deployment. Not a security
reference: PKCE/state are accepted without verification, tokens are opaque
strings, nothing is persisted across restarts.

Env vars: PORT (default 8000), ORIGIN (default http://127.0.0.1:$PORT,
override when a client reaches this on a different host/port than the
container's own), PROVIDER (default acktest), MODEL_ID (default echo-model),
SHORT_TOKEN_SECONDS (default 90 -- deliberately short so a client that
resolves a credential soon after login exercises its refresh path),
LONG_TOKEN_SECONDS (default 3600, issued on refresh).
"""

import http.server
import json
import os
import threading
import time
import urllib.parse

PORT = int(os.environ.get("PORT", "8000"))
ORIGIN = os.environ.get("ORIGIN", f"http://127.0.0.1:{PORT}")
PROVIDER = os.environ.get("PROVIDER", "acktest")
MODEL_ID = os.environ.get("MODEL_ID", "echo-model")
SHORT_TOKEN_SECONDS = int(os.environ.get("SHORT_TOKEN_SECONDS", "90"))
LONG_TOKEN_SECONDS = int(os.environ.get("LONG_TOKEN_SECONDS", "3600"))

STATE = {"refresh_calls": 0, "device_calls": 0, "auth_code_calls": 0, "chat_calls": 0}
LOCK = threading.Lock()
# device_code -> polls remaining before success, so the client's polling loop
# actually runs at least once (RFC 8628 authorization_pending).
PENDING_DEVICES: dict[str, int] = {}


def issue_tokens(short: bool) -> dict:
    seconds = SHORT_TOKEN_SECONDS if short else LONG_TOKEN_SECONDS
    return {
        "access_token": f"access-{int(time.time() * 1000)}",
        "refresh_token": f"refresh-{int(time.time() * 1000)}",
        "expires_in": seconds,
    }


def read_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b""
    ct = handler.headers.get("Content-Type", "")
    if "application/json" in ct:
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}


def send(handler, code: int, body, content_type="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def config_body() -> dict:
    return {
        "schema": "ackstorm.opencode-config/1",
        "version": "sha256:mock",
        "user": "mock@example.com",
        "environment": None,
        "auth": "ok",
        "stale": False,
        "generatedAt": "2026-01-01T00:00:00Z",
        "config": {
            "provider": {
                PROVIDER: {
                    "name": "ACKstorm Mock",
                    # v1 field, kept for the v1 loader; the v2 plugin hardcodes its own
                    # package (see clients/opencode/index.mjs) since the real
                    # @ai-sdk/openai-compatible has no compatible .model() factory.
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {"baseURL": f"{ORIGIN}/v1"},
                    "models": {
                        MODEL_ID: {
                            "name": "Echo Model",
                            "attachment": False,
                            "reasoning": False,
                            "tool_call": False,
                            "temperature": True,
                            "modalities": {"input": ["text"], "output": ["text"]},
                            "limit": {"context": 200000, "output": 32000},
                            "cost": {"input": 0, "output": 0, "cache_read": 0},
                        }
                    },
                }
            },
            "mcp": {
                # Registered so clients see an MCP entry end to end, but this mock does
                # not implement the MCP protocol itself -- connecting will fail.
                "mock-mcp": {"type": "remote", "url": f"{ORIGIN}/mcp/mock", "enabled": False}
            },
        },
        "skills": [
            {
                "name": "mock-skill",
                "version": "sha256:mockskill",
                "files": {
                    "SKILL.md": "---\nname: mock-skill\ndescription: A skill from the opencode mock backend.\n---\n\nThis skill came from the opencode-mock docker service.\n"
                },
            }
        ],
    }


def chat_response(stream: bool, last_message: str) -> bytes:
    text = f"mock reply to: {last_message}" if last_message else "mock reply"
    if stream:
        chunks = [
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
            },
            {"id": "c1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"
    return json.dumps(
        {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    ).encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 -- matches base signature
        print(f"[opencode-mock] {self.address_string()} {format % args}")

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/.well-known/oauth-protected-resource":
            return send(self, 200, {"authorization_servers": [ORIGIN]})

        if path == "/.well-known/oauth-authorization-server":
            return send(
                self,
                200,
                {
                    "issuer": ORIGIN,
                    "authorization_endpoint": f"{ORIGIN}/authorize",
                    "token_endpoint": f"{ORIGIN}/token",
                    "registration_endpoint": f"{ORIGIN}/register",
                    "device_authorization_endpoint": f"{ORIGIN}/device_authorization",
                },
            )

        if path == "/authorize":
            # Mock: no real login UI, immediately redirect with a fake code.
            redirect_uri = query.get("redirect_uri", [None])[0]
            state = query.get("state", [""])[0]
            if not redirect_uri:
                return send(self, 400, {"error": "missing redirect_uri"})
            location = f"{redirect_uri}?code=mock-auth-code&state={urllib.parse.quote(state)}"
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/clients/opencode/config":
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return send(self, 401, {"error": "missing bearer"})
            return send(self, 200, config_body())

        if path.startswith("/v1/chat/completions"):
            return send(self, 405, {"error": "use POST"})

        if path == "/stats":
            with LOCK:
                return send(self, 200, dict(STATE))

        return send(self, 404, {"error": "not found"})

    def do_POST(self):
        data = read_body(self)

        if self.path == "/register":
            return send(self, 200, {"client_id": "mock-client-id"})

        if self.path == "/device_authorization":
            with LOCK:
                STATE["device_calls"] += 1
            device_code = f"device-{int(time.time() * 1000)}"
            PENDING_DEVICES[device_code] = 1  # one authorization_pending before success
            return send(
                self,
                200,
                {
                    "device_code": device_code,
                    "user_code": "ABCD-EFGH",
                    "verification_uri": f"{ORIGIN}/verify",
                    "verification_uri_complete": f"{ORIGIN}/verify?user_code=ABCD-EFGH",
                    "expires_in": 600,
                    "interval": 1,
                },
            )

        if self.path == "/token":
            grant = data.get("grant_type")
            if grant == "urn:ietf:params:oauth:grant-type:device_code":
                device_code = data.get("device_code", "")
                remaining = PENDING_DEVICES.get(device_code, 0)
                if remaining > 0:
                    PENDING_DEVICES[device_code] = remaining - 1
                    return send(self, 400, {"error": "authorization_pending"})
                return send(self, 200, issue_tokens(short=True))
            if grant == "authorization_code":
                with LOCK:
                    STATE["auth_code_calls"] += 1
                return send(self, 200, issue_tokens(short=True))
            if grant == "refresh_token":
                with LOCK:
                    STATE["refresh_calls"] += 1
                return send(self, 200, issue_tokens(short=False))
            return send(self, 400, {"error": "unsupported_grant_type"})

        if self.path.startswith("/v1/chat/completions"):
            with LOCK:
                STATE["chat_calls"] += 1
            stream = bool(data.get("stream"))
            messages = data.get("messages") or []
            last = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    content = m.get("content")
                    last = content if isinstance(content, str) else json.dumps(content)
                    break
            body = chat_response(stream, last)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return send(self, 404, {"error": "not found"})


class ThreadingServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print(f"[opencode-mock] provider={PROVIDER!r} model={MODEL_ID!r} origin={ORIGIN} listening on 0.0.0.0:{PORT}")
    ThreadingServer(("0.0.0.0", PORT), Handler).serve_forever()
