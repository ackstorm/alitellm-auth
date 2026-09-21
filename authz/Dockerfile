# ── Builder ───────────────────────────────────────────────────────────────────
FROM golang:1.25-alpine AS builder
WORKDIR /src
# Explicit paths only — never COPY . . (CLAUDE.md). Modules first for layer caching.
COPY authz/go.mod authz/go.sum ./
RUN go mod download
COPY authz/*.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /authz .

# ── Runtime ───────────────────────────────────────────────────────────────────
# The issuer JWKS endpoints are HTTPS, so scratch needs the builder's CA bundle.
FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /authz /authz
USER 10001
EXPOSE 9001
ENTRYPOINT ["/authz"]
