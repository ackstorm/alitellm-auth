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
	InboundHeader       string // the header an agent presents its key in
	OutboundHeader      string // the header LiteLLM wants the key in
	LegacyPassthrough   bool   // accept a LiteLLM key in the outbound header or as a bearer, untouched
	Issuers             []string
	Audience            string // `aud` accepted on any path (front tokens)
	ResourceBase        string // a broker token's aud must be ResourceBase+path
	ResourceMetadataURL string // the front's RFC 9728 document, for non-MCP paths
	KeyResolverURL      string
	InternalToken       string
	KeyCacheTTL         time.Duration
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func LoadConfig() Config {
	ttl, _ := strconv.Atoi(envOr("AUTHZ_KEY_CACHE_TTL_SECONDS", "300"))
	var issuers []string
	for _, s := range strings.Split(os.Getenv("AUTHZ_ISSUERS"), ",") {
		if s = strings.TrimSpace(s); s != "" {
			issuers = append(issuers, strings.TrimRight(s, "/"))
		}
	}
	return Config{
		ListenAddr:          envOr("AUTHZ_LISTEN", ":9001"),
		InboundHeader:       strings.ToLower(envOr("AUTHZ_INBOUND_HEADER", "x-genai-api-key")),
		OutboundHeader:      strings.ToLower(envOr("AUTHZ_OUTBOUND_HEADER", "x-litellm-api-key")),
		LegacyPassthrough:   envOr("AUTHZ_LEGACY_PASSTHROUGH", "true") == "true",
		Issuers:             issuers,
		Audience:            envOr("AUTHZ_AUDIENCE", "alitellm"),
		ResourceBase:        strings.TrimRight(os.Getenv("AUTHZ_RESOURCE_BASE"), "/"),
		ResourceMetadataURL: os.Getenv("AUTHZ_RESOURCE_METADATA_URL"),
		KeyResolverURL:      os.Getenv("AUTHZ_KEY_RESOLVER_URL"),
		InternalToken:       os.Getenv("AUTHZ_INTERNAL_TOKEN"),
		KeyCacheTTL:         time.Duration(ttl) * time.Second,
	}
}
