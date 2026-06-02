# OIDC Integration Guide (Dex / Keycloak)

`alitellm-auth` authenticates users through any OIDC-compliant identity provider
(IdP) and provisions a per-user LiteLLM credential on login. This guide explains
everything an operator needs to wire the service to **Dex** or **Keycloak**: the
client registration, the environment-variable mapping, the TLS/redirect-URI
rationale, and a troubleshooting table for the most common failure modes.

The service is provider-agnostic — every setting uses the `OAUTH_` prefix, so the
same configuration shape works for Dex, Keycloak, or any other OIDC provider. Only
the issuer URL, client id, and client secret change between providers.

---

## 1. What the app needs from the IdP

To complete the authorization-code flow and read the user's identity,
`alitellm-auth` requires the IdP to provide:

- An **OIDC client** with a `client_id`, a `client_secret`, and a **redirect URI**
  set to `${APP_BASE_URL}/api/oauth/callback`.
- The scopes **`openid email profile`** (these are the scopes the app requests on
  every login).
- An **`email` claim** returned from the userinfo endpoint. The login flow extracts
  `email` (and `name`) from the OIDC token's userinfo; a missing `email` claim
  fails the login with a "No email claim" error.

---

## 2. Dex configuration (`staticClients`)

Register `alitellm-auth` as a static client in your Dex configuration. Use
placeholder values like the ones below — replace them with your own hostnames and
inject the secret from your secret store, never inline a real secret in
version-controlled config.

```yaml
staticClients:
  - id: platform
    name: alitellm-auth
    secret: ${YOUR_CLIENT_SECRET}
    redirectURIs:
      - https://your-app.example.com/api/oauth/callback
```

> **Note:** The `id` must match `OAUTH_CLIENT_ID` in `alitellm-auth`. The `secret`
> injected as a Dex env var must match `OAUTH_CLIENT_SECRET`. The `redirectURIs`
> entry must match `${APP_BASE_URL}/api/oauth/callback` exactly — scheme, host, and
> path all have to line up (see Section 5 for why the scheme matters).

The Dex **issuer URL** (the value you set as `OAUTH_ISSUER_URL`) is the public URL
where Dex serves its discovery document, e.g.
`https://dex.example.com/dex`. The app appends
`/.well-known/openid-configuration` to discover the authorization, token, and
userinfo endpoints automatically.

---

## 3. Keycloak equivalent

The same flow works against Keycloak with an equivalent client setup:

1. In the Keycloak admin console, create a client named **`platform`** (or
   whatever value you set for `OAUTH_CLIENT_ID`).
2. Set **Valid Redirect URIs** to `${APP_BASE_URL}/api/oauth/callback`.
3. Enable the **Standard Flow** (the OIDC authorization-code flow).
4. Copy the generated **client secret** — this becomes `OAUTH_CLIENT_SECRET`.

The Keycloak **issuer URL** (`OAUTH_ISSUER_URL`) has the form
`https://<keycloak-host>/realms/<realm>`.

---

## 4. Environment variable mapping

The following table maps each environment variable to its source and shows an
example placeholder value. The variable names are authoritative — they match
`src/api/app/config.py`.

| Variable | Where it comes from | Example value |
|----------|---------------------|---------------|
| `APP_BASE_URL` | Public URL of the app | `https://your-app.example.com` |
| `OAUTH_ISSUER_URL` | Dex issuer URL (from Dex config) | `https://dex.example.com/dex` |
| `OAUTH_CLIENT_ID` | Dex/Keycloak client id | `platform` |
| `OAUTH_CLIENT_SECRET` | Dex/Keycloak client secret | `(from k8s secret)` |
| `SESSION_SECRET_KEY` | Random hex, shared across all replicas | `(openssl rand -hex 32)` |
| `LITELLM_URL` | Internal LiteLLM base URL | `http://litellm:4000` |
| `LITELLM_MASTER_KEY` | LiteLLM admin master key | `(from k8s secret)` |

> **`SESSION_SECRET_KEY` must be identical on every replica.** Authlib stores the
> OAuth `state` and `nonce` in the session cookie between `/login` and
> `/callback`. If `/login` is served by one replica and `/callback` by another
> with a different key, the cookie cannot be verified and the login fails. Set it
> once from a shared secret (e.g. a Kubernetes secret) rather than generating it
> per-process.

---

## 5. Why `APP_BASE_URL` builds the redirect URI

`alitellm-auth` always constructs the callback URL from `APP_BASE_URL` rather than
inferring it from the incoming request. This is deliberate.

In a typical deployment, an ingress controller or reverse proxy (such as nginx)
**terminates TLS** at the edge and forwards plain **HTTP** to the application pod.
From inside the pod, the request therefore looks like an `http://` request, even
though the browser reached the service over `https://`. If the app derived the
callback URL from the request scheme it observed, it would produce an `http://`
redirect URI.

The IdP — Dex or Keycloak — only has the `https://` redirect URI registered.
Sending an `http://` redirect URI that does not match the registered value causes
the IdP to reject the request with an **`Unregistered redirect_uri`** error.

The fix is to never trust the request-derived scheme for the callback URL. Instead,
the app builds the callback from `APP_BASE_URL`, which the operator configures with
the correct public `https://` scheme and host. As long as `APP_BASE_URL` matches
the redirect URI registered at the IdP, the schemes line up and the IdP accepts the
authorization request.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Unregistered redirect_uri` | `APP_BASE_URL` has the wrong scheme (http vs https) or the wrong host, so the computed callback URL does not match what the IdP has registered | Set `APP_BASE_URL` to the public `https://` URL; verify the IdP redirect URI registration matches `${APP_BASE_URL}/api/oauth/callback` exactly |
| `MismatchingStateError` on `/callback` | `SessionMiddleware` is not added before the routes, **or** `SESSION_SECRET_KEY` differs between replicas, so the OAuth state stored at `/login` cannot be read back at `/callback` | Ensure `SessionMiddleware` is added first in `create_app()`; use a single shared `SESSION_SECRET_KEY` sourced from a k8s secret across all replicas |
| `No email claim` | The OIDC provider is not configured to return the `email` scope, so the userinfo response has no email field | Add `email` to the client's scopes in Dex/Keycloak; verify the userinfo endpoint returns an `email` field for the user |

---

## See also

- [Project README](https://github.com/ackstorm/alitellm-auth#readme) — service overview and API endpoints.
