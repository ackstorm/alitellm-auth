package main

import (
	"context"
	"regexp"
	"strings"
)

// Verifier proves one of our bearer tokens and returns its subject and scopes.
type Verifier interface {
	Verify(token string) (sub string, scopes []string, err error)
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

// protectedPrefixes are the model API and the MCP/A2A servers: a request
// there must carry a credential. Everything else on the host (LiteLLM's UI,
// /health/*, /key/*, /v2/*, …) is the catch-all — a presented credential is
// resolved, nothing presented is forwarded untouched and LiteLLM decides.
var protectedPrefixes = []string{"/v1/", "/gemini/", "/mcp/", "/a2a/"}

func protected(path string) bool {
	for _, p := range protectedPrefixes {
		if path == strings.TrimSuffix(p, "/") || strings.HasPrefix(path, p) {
			return true
		}
	}
	return false
}

// Decide is the whole policy. Order matters and is the contract.
//
// Authorization is not ours: it may carry the upstream provider's credential
// (Claude Code with an Anthropic subscription sends Anthropic's OAuth there and
// our key in the custom header), LiteLLM's own UI bearer, or a LiteLLM key in
// the OpenAI-SDK shape. It is consumed in exactly one case — when it carries
// OUR JWS — so LiteLLM receives exactly one thing from us, the outbound header.
//
//  1. a declared inbound header present → a LiteLLM key (sk-…) is renamed;
//     our JWT is verified and mapped. That header is removed. Authorization untouched.
//  2. Authorization: Bearer <JWS> → ours: verified, mapped, removed
//  3. Authorization carrying anything else → not ours: forwarded untouched,
//     LiteLLM authenticates it
//  4. the outbound header already present → forwarded untouched (LiteLLM's key)
//  5. nothing presented → 401 with the pointer that starts the ceremony on a
//     protected family; forwarded untouched on the catch-all
//
// A user token on /mcp/<svc> must carry scope <svc> (a grant for that service),
// or the answer is the 403 that makes an MCP client step up. Agent keys are
// not scope-gated: their grant comes through the `authenticate` tool.
func Decide(ctx context.Context, cfg Config, path string, h map[string]string, v Verifier, r KeyResolver) Decision {
	// x-user-id is LiteLLM's impersonation contract with the console; nothing
	// from the internet may carry it. Also stripped at the route.
	strip := []string{"x-user-id"}
	untouched := Decision{Allow: true, Set: map[string]string{}, Remove: strip}

	// The declared slots, in precedence order. x-api-key is where the Anthropic
	// SDK puts an API key (Claude Code with ANTHROPIC_API_KEY or an apiKeyHelper
	// sends it there, never in Authorization), so it is in the default list.
	// Same two shapes in every slot.
	for _, name := range cfg.InboundHeaders {
		raw := h[name]
		if raw == "" {
			continue
		}
		tok := bareKey(raw)
		remove := append(strip, name)
		if !looksLikeJWS(tok) {
			return allowWithKey(cfg, tok, remove)
		}
		return userPath(ctx, cfg, path, tok, remove, v, r)
	}
	if auth := h["authorization"]; auth != "" {
		if tok := bareKey(auth); strings.HasPrefix(auth, "Bearer ") && looksLikeJWS(tok) {
			return userPath(ctx, cfg, path, tok, append(strip, "authorization"), v, r)
		}
		return untouched // not ours; LiteLLM authenticates it
	}
	if h[cfg.OutboundHeader] != "" || !protected(path) {
		return untouched
	}
	return deny(401, challenge(cfg, path, ""),
		`{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in `+strings.Join(cfg.InboundHeaders, ", ")+` or Authorization: Bearer"}`)
}

func userPath(ctx context.Context, cfg Config, path, tok string, remove []string, v Verifier, r KeyResolver) Decision {
	sub, scopes, err := v.Verify(tok)
	if err != nil {
		return deny(401, challenge(cfg, path, "invalid_token"),
			`{"error":"invalid_token","error_description":"the bearer token could not be verified"}`)
	}
	if svc := mcpService(path); svc != "" && !hasScope(scopes, svc) {
		return deny(403, `Bearer error="insufficient_scope", scope="`+svc+`", resource_metadata="`+challengeDoc(cfg, path)+`"`,
			`{"error":"insufficient_scope","scope":"`+svc+`"}`)
	}
	key, err := r.KeyFor(ctx, sub)
	if err != nil {
		return deny(503, "", `{"error":"key_resolver_unavailable"}`)
	}
	return allowWithKey(cfg, key, remove)
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

// looksLikeJWS: header.payload.signature and not a LiteLLM key. Anything that
// starts with sk- is LiteLLM's, whatever follows — LiteLLM decides.
func looksLikeJWS(s string) bool {
	return strings.Count(s, ".") == 2 && !strings.HasPrefix(s, "sk-")
}

// serviceName bounds what lands in the challenge header and the JSON body
// unescaped; a name outside it is not a service and falls through as a
// non-MCP path.
var serviceName = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)

// mcpService: "/mcp/mcp-aws-eks-ro[/…]" → "mcp-aws-eks-ro"; "" for any other
// path, or a segment that is not a well-formed service name.
func mcpService(path string) string {
	rest, ok := strings.CutPrefix(path, "/mcp/")
	if !ok {
		return ""
	}
	svc, _, _ := strings.Cut(rest, "/")
	if !serviceName.MatchString(svc) {
		return ""
	}
	return svc
}

func hasScope(scopes []string, want string) bool {
	for _, s := range scopes {
		if s == want {
			return true
		}
	}
	return false
}

// challengeDoc names the document a client must fetch to start a ceremony. We
// serve every one of them: the root for the model API, one per MCP service.
// The service root, never the dialled path: streamable HTTP appends
// `/messages` and session segments, and a client compares the document's
// `resource` against the server it holds, which is the root.
func challengeDoc(cfg Config, path string) string {
	if svc := mcpService(path); svc != "" {
		return cfg.ResourceMetadataURL + "/mcp/" + svc
	}
	return cfg.ResourceMetadataURL
}

func challenge(cfg Config, path, errCode string) string {
	doc := challengeDoc(cfg, path)
	if errCode != "" {
		return `Bearer error="` + errCode + `", resource_metadata="` + doc + `"`
	}
	return `Bearer resource_metadata="` + doc + `"`
}

func deny(status int, challenge, body string) Decision {
	return Decision{Allow: false, Status: status, WWWAuthenticate: challenge, Body: body}
}
