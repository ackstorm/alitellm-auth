# openwork-den

A zero-dependency Node implementation of the OpenWork organization-server
("Den") contract — the executable reference the FastAPI implementation in
`src/api/app/openwork.py` was verified against, using the real desktop app.
Not part of the deployed application. Unlike the FastAPI one it also serves
the cloud MCP agent and native skills, so it doubles as the reference for
those if we ever add them.

    node test/openwork-den/den.mjs        # listens on http://localhost:8787
    bash test/openwork-den/smoke.sh       # grant → token → replay-rejected check

Point OpenWork's Settings > Advanced > Organization server URL at it.
Every request is logged, including MCP JSON-RPC method names.

`brand/` holds the logo/icon marks, `skills/` sample native skills it
publishes. Token state is written next to the script and gitignored.
