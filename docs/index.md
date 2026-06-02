# alitellm-auth

`alitellm-auth` is a FastAPI service that sits at the OIDC login boundary of your LiteLLM
deployment. When a user authenticates through an OIDC provider (Dex, Keycloak, or any
compliant IdP), the service provisions a first-class LiteLLM User (`user_id = email`) and
issues a scoped virtual key (`sk-...`) for that user — all in a single login flow.

## Where it fits

`alitellm-auth` and `alitellm-operator` divide LiteLLM ownership cleanly:

- **alitellm-operator** owns the declarative layer: model routing, team definitions, and
  resource discovery via Kubernetes CRDs. It does not manage Users or VirtualKeys.
- **alitellm-auth** owns the identity layer: Users and VirtualKeys. Every login creates or
  reuses the user record and returns a credential the user can put directly into an LLM client.

## Getting a key

Navigate to `/api/oauth/login`. After OIDC authentication, you land on a page showing your
`sk-...` key. Returning users can use `/api/oauth/reveal` to retrieve their most recent key
without creating a new one. All keys for your account are listed at `/api/oauth/tokens`.

For the full endpoint reference, request/response shapes, and `whoami` identity resolution,
see the [README on GitHub](https://github.com/ackstorm/alitellm-auth#readme).

## OIDC setup

To wire the service to Dex or Keycloak, including env-var mapping, client registration, and
troubleshooting, see the [Dex / OIDC integration guide](dex-integration.md).
