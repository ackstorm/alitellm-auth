# Deploying alitellm-auth

The [Helm chart](helm/alitellm-auth) is the only install path: parameterized
installs, OCI distribution, GitOps via Helm.

It expects a pre-created Secret named `alitellm-auth-secret` with three keys:
`SESSION_SECRET_KEY`, `OAUTH_CLIENT_SECRET`, `LITELLM_MASTER_KEY`.

```bash
kubectl create secret generic alitellm-auth-secret -n <namespace> \
  --from-literal=SESSION_SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=OAUTH_CLIENT_SECRET=<oidc-client-secret> \
  --from-literal=LITELLM_MASTER_KEY=sk-admin-...
```

## Helm

From a checkout:

```bash
helm install alitellm-auth ./deploy/helm/alitellm-auth \
  --namespace alitellm-auth --create-namespace \
  --set config.appBaseUrl=https://platform.example.com \
  --set ingress.host=platform.example.com
```

From the OCI registry (pushed by `release.yml` on each `vX.Y.Z` tag):

```bash
helm install alitellm-auth oci://ghcr.io/ackstorm/charts/alitellm-auth \
  --version X.Y.Z --namespace alitellm-auth --create-namespace
```

Lint / render locally:

```bash
make helm-lint
make helm-template
```

The chart's `image.tag` defaults to the released `vX.Y.Z`. Before the first release
exists in GHCR, override it: `--set image.tag=latest`.

## Versioning

`make release-bump VERSION=X.Y.Z` updates the chart image tag
(`helm/alitellm-auth/Chart.yaml` + `values.yaml`) alongside the app version, so the
chart and the runtime image stay lockstep. See the repo root `PUBLISH.md` →
*Release flow*.
