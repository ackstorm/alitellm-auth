# fake-den

A zero-dependency Node implementation of the OpenWork Den contract, used to
verify behaviour against the real desktop app before implementing it in
FastAPI. Not part of the deployed application.

    node test/fake-den/fake-den.mjs        # listens on http://localhost:8787
    bash test/fake-den/smoke-fake-den.sh   # grant → token → replay-rejected check

Point OpenWork's Settings > Advanced > Organization server URL at it.
Every request is logged, including MCP JSON-RPC method names.

`brand/` holds the reference logo/icon marks, `skills/` the sample native
skills it publishes. Token state is written next to the script and gitignored.
