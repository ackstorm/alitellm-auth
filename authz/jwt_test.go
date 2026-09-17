package main

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"math/big"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// serveIssuer stands up an issuer: RFC 8414 document + JWKS.
func serveIssuer(t *testing.T, pub *rsa.PublicKey, kid string) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	var srv *httptest.Server
	mux.HandleFunc("/.well-known/oauth-authorization-server", func(w http.ResponseWriter, _ *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"issuer": srv.URL, "jwks_uri": srv.URL + "/jwks.json"})
	})
	mux.HandleFunc("/jwks.json", func(w http.ResponseWriter, _ *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"keys": []map[string]string{{
			"kty": "RSA", "kid": kid, "alg": "RS256", "use": "sig",
			"n": base64.RawURLEncoding.EncodeToString(pub.N.Bytes()),
			"e": base64.RawURLEncoding.EncodeToString(big.NewInt(int64(pub.E)).Bytes()),
		}}})
	})
	srv = httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func sign(t *testing.T, priv *rsa.PrivateKey, kid string, claims jwt.MapClaims) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	tok.Header["kid"] = kid
	s, err := tok.SignedString(priv)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func newVerifier(t *testing.T) (Verifier, *rsa.PrivateKey, string) {
	t.Helper()
	priv, _ := rsa.GenerateKey(rand.Reader, 2048)
	iss := serveIssuer(t, &priv.PublicKey, "k1")
	v, err := NewVerifier(context.Background(), []string{iss.URL}, "alitellm", "https://api.test")
	if err != nil {
		t.Fatal(err)
	}
	return v, priv, iss.URL
}

func exp() int64 { return time.Now().Add(time.Minute).Unix() }

func TestFrontAudienceIsAcceptedOnAnyPath(t *testing.T) {
	v, priv, iss := newVerifier(t)
	tok := sign(t, priv, "k1", jwt.MapClaims{"iss": iss, "aud": "alitellm", "sub": "U@X.COM", "exp": exp()})
	for _, p := range []string{"/v1/chat/completions", "/mcp/mcp-gitlab-ro"} {
		if sub, err := v.Verify(tok, p); err != nil || sub != "u@x.com" {
			t.Fatalf("%s: sub=%q err=%v", p, sub, err)
		}
	}
}

func TestBrokerAudienceIsBoundToItsOwnPath(t *testing.T) {
	v, priv, iss := newVerifier(t)
	tok := sign(t, priv, "k1", jwt.MapClaims{"iss": iss, "aud": "https://api.test/mcp/mcp-gitlab-ro", "sub": "u@x.com", "exp": exp()})
	if _, err := v.Verify(tok, "/mcp/mcp-gitlab-ro"); err != nil {
		t.Fatalf("own path: %v", err)
	}
	for _, p := range []string{"/v1/chat/completions", "/mcp/mcp-aws-eks-ro"} {
		if _, err := v.Verify(tok, p); err == nil {
			t.Fatalf("%s: a token for one MCP server must not open another path", p)
		}
	}
}

func TestVerifyRejectsUnknownIssuerAndMissingExp(t *testing.T) {
	v, priv, iss := newVerifier(t)
	bad := []jwt.MapClaims{
		{"iss": "https://nobody.test", "aud": "alitellm", "sub": "u", "exp": exp()},
		{"iss": iss, "aud": "alitellm", "sub": "u"},
	}
	for i, c := range bad {
		if _, err := v.Verify(sign(t, priv, "k1", c), "/v1/models"); err == nil {
			t.Fatalf("case %d: expected error", i)
		}
	}
}
