package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/MicahParks/keyfunc/v3"
	"github.com/golang-jwt/jwt/v5"
)

// multiVerifier trusts a fixed list of issuers — the front door and each MCP
// broker — each verified against its own JWKS, discovered once at startup
// from the issuer's RFC 8414 document and refreshed by keyfunc on unknown kid.
type multiVerifier struct {
	keys         map[string]keyfunc.Keyfunc
	audience     string
	resourceBase string
}

func NewVerifier(ctx context.Context, issuers []string, audience, resourceBase string) (Verifier, error) {
	m := &multiVerifier{keys: map[string]keyfunc.Keyfunc{}, audience: audience, resourceBase: strings.TrimRight(resourceBase, "/")}
	client := &http.Client{Timeout: 5 * time.Second}
	for _, iss := range issuers {
		jwksURL, err := discoverJWKS(ctx, client, iss)
		if err != nil {
			return nil, fmt.Errorf("issuer %s: %w", iss, err)
		}
		kf, err := keyfunc.NewDefaultCtx(ctx, []string{jwksURL})
		if err != nil {
			return nil, fmt.Errorf("issuer %s jwks %s: %w", iss, jwksURL, err)
		}
		m.keys[strings.TrimRight(iss, "/")] = kf
	}
	return m, nil
}

func discoverJWKS(ctx context.Context, c *http.Client, issuer string) (string, error) {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, issuer+"/.well-known/oauth-authorization-server", nil)
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("metadata returned %d", resp.StatusCode)
	}
	var doc struct {
		JWKSURI string `json:"jwks_uri"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&doc); err != nil || doc.JWKSURI == "" {
		return "", errors.New("metadata has no jwks_uri")
	}
	return doc.JWKSURI, nil
}

func (m *multiVerifier) Verify(raw, path string) (string, error) {
	// Peek at iss without verifying, to pick the JWKS; verification follows.
	unverified, _, err := jwt.NewParser().ParseUnverified(raw, jwt.MapClaims{})
	if err != nil {
		return "", err
	}
	iss, _ := unverified.Claims.GetIssuer()
	kf, ok := m.keys[strings.TrimRight(iss, "/")]
	if !ok {
		return "", fmt.Errorf("issuer not trusted: %q", iss)
	}
	tok, err := jwt.Parse(raw, kf.Keyfunc,
		jwt.WithValidMethods([]string{"RS256", "ES256", "EdDSA"}),
		jwt.WithExpirationRequired(),
		jwt.WithIssuer(iss),
	)
	if err != nil {
		return "", err
	}
	auds, err := tok.Claims.GetAudience()
	if err != nil || !m.audienceOK(auds, path) {
		return "", errors.New("audience not accepted for this path")
	}
	sub, err := tok.Claims.GetSubject()
	if err != nil || sub == "" {
		return "", errors.New("no subject")
	}
	return strings.ToLower(sub), nil
}

// audienceOK: the platform audience opens every path; a resource audience
// opens exactly the path it names. A token for one MCP server is not a token
// for the model API or for another server (RFC 8707).
func (m *multiVerifier) audienceOK(auds []string, path string) bool {
	for _, a := range auds {
		if a == m.audience {
			return true
		}
		if m.resourceBase != "" && a == m.resourceBase+path {
			return true
		}
	}
	return false
}
