package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/MicahParks/keyfunc/v3"
	"github.com/golang-jwt/jwt/v5"
)

// verifier trusts exactly one issuer — verified against its JWKS, discovered
// from its metadata document and refreshed by keyfunc on an unknown kid. One
// audience. Scopes come back as a slice.
type verifier struct {
	issuer   string
	keys     atomic.Pointer[jwks]
	audience string
	// subjectClaim names the claim carrying the LiteLLM user id. Empty (or
	// "sub") reads the standard subject; see subject() for why an IdP needs
	// to name a different one.
	subjectClaim string
}

// jwks is one keyfunc bound to the jwks_uri it was built from; cancel stops
// its background refresh once a newer one replaces it.
type jwks struct {
	url    string
	kf     keyfunc.Keyfunc
	cancel context.CancelFunc
}

// rediscoverEvery is how often the metadata document is re-read. keyfunc
// refreshes one URL forever, so without this a jwks_uri that moves (the AS
// changing hostname, or authz reading the document a beat before the app
// serves the new issuer) strands authz on a dead URL until a restart.
var rediscoverEvery = 5 * time.Minute

func NewVerifier(ctx context.Context, issuer, audience, subjectClaim string) (Verifier, error) {
	issuer = strings.TrimRight(issuer, "/")
	v := &verifier{issuer: issuer, audience: audience, subjectClaim: subjectClaim}
	if err := v.discover(ctx); err != nil {
		return nil, err
	}
	go v.rediscover(ctx, rediscoverEvery)
	return v, nil
}

// discover resolves the issuer's jwks_uri and, if it differs from the one in
// use, swaps in a keyfunc for it. A failure keeps the current key set.
func (v *verifier) discover(ctx context.Context) error {
	url, err := discoverJWKS(ctx, &http.Client{Timeout: 5 * time.Second}, v.issuer)
	if err != nil {
		return fmt.Errorf("issuer %s: %w", v.issuer, err)
	}
	cur := v.keys.Load()
	if cur != nil && cur.url == url {
		return nil
	}
	kctx, cancel := context.WithCancel(ctx)
	kf, err := keyfunc.NewDefaultCtx(kctx, []string{url})
	if err != nil {
		cancel()
		return fmt.Errorf("issuer %s jwks %s: %w", v.issuer, url, err)
	}
	v.keys.Store(&jwks{url: url, kf: kf, cancel: cancel})
	if cur != nil {
		cur.cancel()
		log.Printf("issuer %s: jwks_uri moved %s → %s", v.issuer, cur.url, url)
	}
	return nil
}

func (v *verifier) rediscover(ctx context.Context, every time.Duration) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if err := v.discover(ctx); err != nil {
				log.Printf("rediscovery: %v", err)
			}
		}
	}
}

// discoveryPaths: the front door publishes RFC 8414 and nothing else; an OIDC
// provider (Dex) publishes only OpenID Connect Discovery. Both documents carry
// jwks_uri under the same name, so the first one that answers wins.
var discoveryPaths = []string{
	"/.well-known/oauth-authorization-server",
	"/.well-known/openid-configuration",
}

func discoverJWKS(ctx context.Context, c *http.Client, issuer string) (string, error) {
	var lastErr error
	for _, path := range discoveryPaths {
		uri, err := fetchJWKSURI(ctx, c, issuer+path)
		if err == nil {
			return uri, nil
		}
		lastErr = err
	}
	return "", lastErr
}

func fetchJWKSURI(ctx context.Context, c *http.Client, url string) (string, error) {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("%s returned %d", url, resp.StatusCode)
	}
	var doc struct {
		JWKSURI string `json:"jwks_uri"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&doc); err != nil || doc.JWKSURI == "" {
		return "", fmt.Errorf("%s has no jwks_uri", url)
	}
	return doc.JWKSURI, nil
}

func (v *verifier) Verify(raw string) (string, []string, error) {
	tok, err := jwt.Parse(raw, v.keys.Load().kf.Keyfunc,
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
	sub, err := v.subject(claims)
	if err != nil {
		return "", nil, err
	}
	scope, _ := claims["scope"].(string)
	return sub, strings.Fields(scope), nil
}

// subject is the LiteLLM user id the token stands for — what the key resolver
// mints and looks a front key up by, which is always the user's email.
//
// The front door mints `sub` as that email, so it is read straight. An IdP need
// not: Dex encodes `sub` as a base64 protobuf of (userID, connectorID), opaque
// and connector-scoped, and it offers no way to override that. Such an issuer
// names the claim that does carry the email instead.
func (v *verifier) subject(claims jwt.MapClaims) (string, error) {
	if v.subjectClaim == "" || v.subjectClaim == "sub" {
		sub, err := claims.GetSubject()
		if err != nil || sub == "" {
			return "", errors.New("no subject")
		}
		return strings.ToLower(sub), nil
	}
	sub, _ := claims[v.subjectClaim].(string)
	if sub = strings.TrimSpace(sub); sub == "" {
		return "", fmt.Errorf("no %s claim", v.subjectClaim)
	}
	return strings.ToLower(sub), nil
}

// multiVerifier hands a token to the verifier for its issuer.
//
// The `iss` it routes on is read UNVERIFIED. That is safe: the verifier it
// picks pins that same issuer against the signature, so a forged `iss` only
// chooses which verifier will reject the token. Routing rather than trying each
// in turn also keeps a token off the wrong issuer's keyfunc, which would treat
// the foreign `kid` as unknown and refetch that issuer's JWKS on every request.
type multiVerifier map[string]Verifier

func NewMultiVerifier(byIssuer map[string]Verifier) Verifier {
	return multiVerifier(byIssuer)
}

func (m multiVerifier) Verify(raw string) (string, []string, error) {
	iss, err := unverifiedIssuer(raw)
	if err != nil {
		return "", nil, err
	}
	v, ok := m[strings.TrimRight(iss, "/")]
	if !ok {
		return "", nil, fmt.Errorf("issuer %s is not trusted", iss)
	}
	return v.Verify(raw)
}

func unverifiedIssuer(raw string) (string, error) {
	var claims jwt.MapClaims
	if _, _, err := jwt.NewParser().ParseUnverified(raw, &claims); err != nil {
		return "", err
	}
	iss, err := claims.GetIssuer()
	if err != nil || iss == "" {
		return "", errors.New("no issuer")
	}
	return iss, nil
}
