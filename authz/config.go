package main

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// Config is read once from the environment. Header names are lower-case
// because Envoy hands them to ext_authz lower-cased.
type Config struct {
	ListenAddr          string
	InboundHeaders      []string // the headers an agent may present its credential in, in precedence order
	OutboundHeader      string   // the header LiteLLM wants the key in
	Issuer              string   // the authorization server whose tokens we accept
	Audience            string   // `aud` every token must carry
	ResourceMetadataURL string   // base of our RFC 9728 documents; MCP ones live at <base>/mcp/<svc>
	KeyResolverURL      string
	InternalToken       string
	KeyCacheTTL         time.Duration

	// A second trusted issuer: the identity provider sitting behind the front
	// door. A browser app that has already signed the user in holds one of its
	// tokens and can forward it as-is (LibreChat does, as its custom-endpoint
	// Authorization header), so there is no code to exchange and no key to
	// paste. Empty IDPIssuer leaves the single-issuer behaviour untouched.
	IDPIssuer       string
	IDPAudience     string // no default: an issuer without an audience is a wildcard
	IDPSubjectClaim string // the claim carrying the LiteLLM user id — see verifier.subject
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func LoadConfig() Config {
	ttl, _ := strconv.Atoi(envOr("AUTHZ_KEY_CACHE_TTL_SECONDS", "300"))
	return Config{
		ListenAddr:          envOr("AUTHZ_LISTEN", ":9001"),
		InboundHeaders:      splitHeaders(envOr("AUTHZ_INBOUND_HEADERS", "x-genai-api-key,x-api-key")),
		OutboundHeader:      strings.ToLower(envOr("AUTHZ_OUTBOUND_HEADER", "x-litellm-api-key")),
		Issuer:              strings.TrimRight(os.Getenv("AUTHZ_ISSUER"), "/"),
		Audience:            envOr("AUTHZ_AUDIENCE", "alitellm"),
		ResourceMetadataURL: strings.TrimRight(os.Getenv("AUTHZ_RESOURCE_METADATA_URL"), "/"),
		KeyResolverURL:      os.Getenv("AUTHZ_KEY_RESOLVER_URL"),
		IDPIssuer:           strings.TrimRight(os.Getenv("AUTHZ_IDP_ISSUER"), "/"),
		IDPAudience:         os.Getenv("AUTHZ_IDP_AUDIENCE"),
		IDPSubjectClaim:     envOr("AUTHZ_IDP_SUBJECT_CLAIM", "email"),
		InternalToken:       os.Getenv("AUTHZ_INTERNAL_TOKEN"),
		KeyCacheTTL:         time.Duration(ttl) * time.Second,
	}
}

// splitHeaders: "A, b,,c" → ["a", "b", "c"]. Envoy hands ext_authz lower-cased
// names, so the list is lower-cased once here.
func splitHeaders(s string) []string {
	var out []string
	for _, h := range strings.Split(s, ",") {
		if h = strings.ToLower(strings.TrimSpace(h)); h != "" {
			out = append(out, h)
		}
	}
	return out
}
