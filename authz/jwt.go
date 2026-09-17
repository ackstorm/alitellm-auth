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

// verifier trusts exactly one issuer — the front door — verified against its
// JWKS, discovered once at startup from its RFC 8414 document and refreshed
// by keyfunc on an unknown kid. One audience. Scopes come back as a slice.
type verifier struct {
	issuer   string
	keys     keyfunc.Keyfunc
	audience string
}

func NewVerifier(ctx context.Context, issuer, audience string) (Verifier, error) {
	issuer = strings.TrimRight(issuer, "/")
	jwksURL, err := discoverJWKS(ctx, &http.Client{Timeout: 5 * time.Second}, issuer)
	if err != nil {
		return nil, fmt.Errorf("issuer %s: %w", issuer, err)
	}
	kf, err := keyfunc.NewDefaultCtx(ctx, []string{jwksURL})
	if err != nil {
		return nil, fmt.Errorf("issuer %s jwks %s: %w", issuer, jwksURL, err)
	}
	return &verifier{issuer: issuer, keys: kf, audience: audience}, nil
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

func (v *verifier) Verify(raw string) (string, []string, error) {
	tok, err := jwt.Parse(raw, v.keys.Keyfunc,
		jwt.WithValidMethods([]string{"RS256"}),
		jwt.WithExpirationRequired(),
		jwt.WithIssuer(v.issuer),
		jwt.WithAudience(v.audience),
	)
	if err != nil {
		return "", nil, err
	}
	claims, ok := tok.Claims.(jwt.MapClaims)
	if !ok {
		return "", nil, errors.New("unexpected claims")
	}
	sub, err := claims.GetSubject()
	if err != nil || sub == "" {
		return "", nil, errors.New("no subject")
	}
	scope, _ := claims["scope"].(string)
	return strings.ToLower(sub), strings.Fields(scope), nil
}
