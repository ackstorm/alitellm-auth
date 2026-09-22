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
	return serveIssuerAt(t, pub, kid, "/.well-known/oauth-authorization-server")
}

// serveIssuerAt stands up an issuer publishing its metadata at one path only,
// so a provider that serves OIDC discovery and not RFC 8414 (Dex) is covered.
func serveIssuerAt(t *testing.T, pub *rsa.PublicKey, kid, metadataPath string) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	var srv *httptest.Server
	mux.HandleFunc(metadataPath, func(w http.ResponseWriter, _ *http.Request) {
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
	v, err := NewVerifier(context.Background(), iss.URL, "alitellm", "")
	if err != nil {
		t.Fatal(err)
	}
	return v, priv, iss.URL
}

func exp() int64 { return time.Now().Add(time.Minute).Unix() }

func TestVerifyReturnsSubjectAndScopes(t *testing.T) {
	v, priv, iss := newVerifier(t)
	tok := sign(t, priv, "k1", jwt.MapClaims{"iss": iss, "aud": "alitellm", "sub": "U@X.com",
		"scope": "alitellm mcp-google-drive", "exp": exp()})
	sub, scopes, err := v.Verify(tok)
	if err != nil || sub != "u@x.com" || len(scopes) != 2 || scopes[1] != "mcp-google-drive" {
		t.Fatalf("sub=%q scopes=%v err=%v", sub, scopes, err)
	}
}

func TestVerifyRejectsWrongAudienceUnknownIssuerAndMissingExp(t *testing.T) {
	v, priv, iss := newVerifier(t)
	bad := []jwt.MapClaims{
		{"iss": iss, "aud": "https://api.test/mcp/mcp-gitlab-ro", "sub": "u", "exp": exp()},
		{"iss": "https://nobody.test", "aud": "alitellm", "sub": "u", "exp": exp()},
		{"iss": iss, "aud": "alitellm", "sub": "u"},
	}
	for i, c := range bad {
		if _, _, err := v.Verify(sign(t, priv, "k1", c)); err == nil {
			t.Fatalf("case %d: expected error", i)
		}
	}
}

// newIDPVerifier stands up a Dex-shaped issuer: OIDC discovery only, and a
// `sub` the key resolver cannot use.
func newIDPVerifier(t *testing.T) (Verifier, *rsa.PrivateKey, string) {
	t.Helper()
	priv, _ := rsa.GenerateKey(rand.Reader, 2048)
	iss := serveIssuerAt(t, &priv.PublicKey, "k1", "/.well-known/openid-configuration")
	v, err := NewVerifier(context.Background(), iss.URL, "chat", "email")
	if err != nil {
		t.Fatal(err)
	}
	return v, priv, iss.URL
}

// Dex's `sub` is a base64 protobuf of (userID, connectorID); the email claim is
// the only thing the key resolver can look a front key up by.
func TestVerifyReadsTheConfiguredSubjectClaim(t *testing.T) {
	v, priv, iss := newIDPVerifier(t)
	tok := sign(t, priv, "k1", jwt.MapClaims{"iss": iss, "aud": "chat",
		"sub": "ChUxMDI5NDc1OTk3MzY2MTIzNDU2NzgSBmdvb2dsZQ", "email": "U@X.com", "exp": exp()})
	sub, _, err := v.Verify(tok)
	if err != nil || sub != "u@x.com" {
		t.Fatalf("sub=%q err=%v", sub, err)
	}
}

func TestVerifyRejectsAMissingSubjectClaim(t *testing.T) {
	v, priv, iss := newIDPVerifier(t)
	tok := sign(t, priv, "k1", jwt.MapClaims{"iss": iss, "aud": "chat", "sub": "opaque", "exp": exp()})
	if _, _, err := v.Verify(tok); err == nil {
		t.Fatal("expected a token with no email claim to be rejected")
	}
}

func TestMultiVerifierRoutesOnIssuerAndRejectsUnknownOnes(t *testing.T) {
	front, frontPriv, frontIss := newVerifier(t)
	idp, idpPriv, idpIss := newIDPVerifier(t)
	m := NewMultiVerifier(map[string]Verifier{frontIss: front, idpIss: idp})

	sub, _, err := m.Verify(sign(t, frontPriv, "k1", jwt.MapClaims{
		"iss": frontIss, "aud": "alitellm", "sub": "u@x.com", "exp": exp()}))
	if err != nil || sub != "u@x.com" {
		t.Fatalf("front door: sub=%q err=%v", sub, err)
	}

	sub, _, err = m.Verify(sign(t, idpPriv, "k1", jwt.MapClaims{
		"iss": idpIss, "aud": "chat", "sub": "opaque", "email": "u@x.com", "exp": exp()}))
	if err != nil || sub != "u@x.com" {
		t.Fatalf("idp: sub=%q err=%v", sub, err)
	}

	// Signed by the IdP but claiming the front door: routed to the front door's
	// verifier, which pins the signature it expects, so it is rejected.
	if _, _, err := m.Verify(sign(t, idpPriv, "k1", jwt.MapClaims{
		"iss": frontIss, "aud": "alitellm", "sub": "u@x.com", "exp": exp()})); err == nil {
		t.Fatal("expected a token signed by the wrong issuer's key to be rejected")
	}

	if _, _, err := m.Verify(sign(t, frontPriv, "k1", jwt.MapClaims{
		"iss": "https://nobody.test", "aud": "alitellm", "sub": "u@x.com", "exp": exp()})); err == nil {
		t.Fatal("expected an untrusted issuer to be rejected")
	}
}
