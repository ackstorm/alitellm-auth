package main

import (
	"context"
	"strings"
)

// Verifier proves a bearer token for a request path and returns its subject.
type Verifier interface {
	Verify(token, path string) (sub string, err error)
}

// KeyResolver maps a subject to the LiteLLM key that carries their requests.
type KeyResolver interface {
	KeyFor(ctx context.Context, sub string) (string, error)
}

// Decision is what Envoy is told. Set and Remove apply to the upstream request.
type Decision struct {
	Allow           bool
	Set             map[string]string
	Remove          []string
	Status          int
	WWWAuthenticate string
	Body            string
}

// Decide is the whole policy. Order matters and is the contract:
//  1. an agent key in the inbound header → renamed, normalised, everything else stripped
//  2. (transition) a LiteLLM key already where LiteLLM wants it → untouched
//  3. a bearer that is not a JWS is a LiteLLM key in the OpenAI-SDK shape →
//     renamed while the transition lasts, refused with a challenge after
//  4. a bearer JWS that verifies → the user's front key, bearer kept so the pod sees the JWT
//  5. anything else → 401 with the pointer that starts the ceremony
func Decide(ctx context.Context, cfg Config, path string, h map[string]string, v Verifier, r KeyResolver) Decision {
	// x-user-id is LiteLLM's impersonation contract with the console; nothing
	// from the internet may carry it. Also stripped at the route (Task 14).
	strip := []string{"x-user-id"}

	if raw := h[cfg.InboundHeader]; raw != "" {
		return allowWithKey(cfg, bareKey(raw), append(strip, cfg.InboundHeader, "authorization"))
	}
	if cfg.LegacyPassthrough && h[cfg.OutboundHeader] != "" {
		return Decision{Allow: true, Set: map[string]string{}, Remove: strip}
	}
	if auth := h["authorization"]; strings.HasPrefix(auth, "Bearer ") {
		tok := strings.TrimSpace(strings.TrimPrefix(auth, "Bearer "))
		if !looksLikeJWS(tok) {
			if !cfg.LegacyPassthrough {
				return deny(401, challenge(cfg, path, ""), `{"error":"unauthorized","error_description":"present a bearer token from the authorization server"}`)
			}
			return allowWithKey(cfg, tok, append(strip, "authorization", cfg.InboundHeader))
		}
		sub, err := v.Verify(tok, path)
		if err != nil {
			return deny(401, challenge(cfg, path, "invalid_token"),
				`{"error":"invalid_token","error_description":"the bearer token could not be verified"}`)
		}
		key, err := r.KeyFor(ctx, sub)
		if err != nil {
			return deny(503, "", `{"error":"key_resolver_unavailable"}`)
		}
		return allowWithKey(cfg, key, append(strip, cfg.InboundHeader))
	}
	return deny(401, challenge(cfg, path, ""),
		`{"error":"unauthorized","error_description":"present an API key or a bearer token"}`)
}

func allowWithKey(cfg Config, key string, remove []string) Decision {
	return Decision{
		Allow:  true,
		Set:    map[string]string{cfg.OutboundHeader: "Bearer " + key},
		Remove: remove,
	}
}

func bareKey(raw string) string {
	return strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(raw), "Bearer "))
}

// looksLikeJWS: header.payload.signature and not a LiteLLM key. A LiteLLM key
// never contains dots; the sk- check is belt and braces.
func looksLikeJWS(s string) bool {
	return strings.Count(s, ".") == 2 && !strings.HasPrefix(s, "sk-")
}

// challenge names the document a client must fetch to start a ceremony. An MCP
// server has its own (LiteLLM serves it) naming that server's broker, so the
// client gets identity and grant in one ceremony.
func challenge(cfg Config, path, errCode string) string {
	doc := cfg.ResourceMetadataURL
	if strings.HasPrefix(path, "/mcp/") {
		doc = cfg.ResourceBase + "/.well-known/oauth-protected-resource" + path
	}
	if errCode != "" {
		return `Bearer error="` + errCode + `", resource_metadata="` + doc + `"`
	}
	return `Bearer resource_metadata="` + doc + `"`
}

func deny(status int, challenge, body string) Decision {
	return Decision{Allow: false, Status: status, WWWAuthenticate: challenge, Body: body}
}
