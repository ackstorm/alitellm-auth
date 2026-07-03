# alitellm-auth

`alitellm-auth` is a FastAPI service that sits at the OIDC login boundary of your LiteLLM
deployment. When a user authenticates through an OIDC provider (Dex, Keycloak, or any
compliant IdP), the service provisions a first-class LiteLLM User (`user_id = email`) and
opens a web console (`/ui`) where the user creates and manages scoped virtual keys (`sk-...`).

## Where it fits

`alitellm-auth` and `alitellm-operator` divide LiteLLM ownership cleanly:

- **alitellm-operator** owns the declarative layer: model routing, team definitions, and
  resource discovery via Kubernetes CRDs. It does not manage Users or VirtualKeys.
- **alitellm-auth** owns the identity layer: Users and VirtualKeys. Every login creates or
  reuses the user record and drops the user into the console to manage their own keys.

## Getting a key

Navigate to `/api/oauth/login`. After OIDC authentication, you land in the `/ui` console,
where you create, list, and delete your `sk-...` keys. Sign-in itself never mints a key —
key management is handled entirely inside the console (backed by the `/api/session/keys` API).

For the full endpoint reference, request/response shapes, and `whoami` identity resolution,
see the [README on GitHub](https://github.com/ackstorm/alitellm-auth#readme).

## OIDC setup

To wire the service to Dex or Keycloak, including env-var mapping, client registration, and
troubleshooting, see the [Dex / OIDC integration guide](dex-integration.md).
