# LiteLLM user-scoping contract (`sso_key_swapper`)

This directory holds the **canonical** LiteLLM custom-auth plugin that the
alitellm-auth console depends on, plus how to install it. The plugin runs on the
**LiteLLM proxy** (a different deployment), but the contract is owned here because
alitellm-auth is its consumer and verifies it at startup.

## Why

The console's **Models** (`/api/session/models`) and **MCPs** (`/api/session/mcp`)
pages must show each signed-in user *their own* entitlements, not the global admin
catalog. The browser never holds the master key or any `sk-`, so alitellm-auth calls
LiteLLM **server-side with the master key plus an `x-user-id: <email>` header** (the
email comes from the authenticated session — never from client input).

`sso_key_swapper` turns that header into an **impersonation** of the user's *default*
key, so LiteLLM returns only what that user can access.

## The contract

| Incoming request to LiteLLM | `sso_key_swapper` behaviour |
|---|---|
| master key, **no** `x-user-id` | genuine admin call → fall back to native auth |
| a real virtual key (`sk-…`) | normal call → fall back to native auth |
| master key **+** `x-user-id` | impersonate that user's **default key**; on ANY failure **hard-reject** (403/503), **never** fall back to admin |

The hard-reject is the security crux: falling back on the master key here would
authenticate the request as **full admin** (privilege escalation). Failures raise
`ProxyException` — a FastAPI `HTTPException` would be **swallowed** as a fallback in
`mode: "auto"`.

## Install (on the LiteLLM deployment)

1. **Ship the file** as a ConfigMap and mount it next to the LiteLLM config.

   Kustomize:
   ```yaml
   configMapGenerator:
     - name: ackstorm-litellm-extras
       namespace: ${namespace}
       files:
         - files/auth_user_map.py   # copy of deploy/litellm/auth_user_map.py
       options:
         disableNameSuffixHash: true
   ```

   Helm values (LiteLLM chart):
   ```yaml
   volumeMounts:
     - name: ackstorm-litellm-auth
       mountPath: /etc/litellm/auth_user_map.py
       subPath: auth_user_map.py
       readOnly: true
   volumes:
     - name: ackstorm-litellm-auth
       configMap:
         name: ackstorm-litellm-extras
         items:
           - key: auth_user_map.py
             path: auth_user_map.py
         optional: false
   ```

2. **Wire it** in the LiteLLM config:
   ```yaml
   custom_auth: auth_user_map.sso_key_swapper
   custom_auth_settings:
     mode: "auto"     # REQUIRED — see note above
   ```

3. The plugin reads the master key from env **`PROXY_MASTER_KEY`** (set it to the
   same value as alitellm-auth's `LITELLM_MASTER_KEY`).

> Keep `deploy/litellm/auth_user_map.py` as the source of truth — copy it into the
> LiteLLM deployment's `files/` rather than maintaining a second copy.

## How alitellm-auth verifies it

At startup alitellm-auth probes the contract (non-fatal) — `app/contract.py` +
`app/litellm_client.py::verify_user_scoping_contract`:

- It calls **`GET /v1/models`** with the master key and a deliberately
  **non-existent** `x-user-id`.
  - **401/403** → contract **enforced** (the impersonation was rejected) → `INFO`.
  - **2xx** → the model list came back, i.e. the master key was accepted as admin and
    `x-user-id` ignored → custom auth **NOT installed** → a **CRITICAL** banner in the
    pod logs (per-user Models/MCPs would silently fall back to the global admin view).
  - **5xx / unreachable** → can't tell (boot ordering / outage) → `WARNING`, retried a
    few times.

This **never** fails readiness or refuses to serve — it only logs. Disable the check
with `LITELLM_USER_SCOPING_CHECK=false` (e.g. OSS forks not using per-user scoping).
