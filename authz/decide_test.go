package main

import (
	"context"
	"errors"
	"testing"
)

type fakeVerifier struct {
	sub    string
	scopes []string
	err    error
}

func (f fakeVerifier) Verify(_ string) (string, []string, error) { return f.sub, f.scopes, f.err }

type fakeResolver struct {
	key   string
	err   error
	calls int
}

func (f *fakeResolver) KeyFor(_ context.Context, _ string) (string, error) {
	f.calls++
	return f.key, f.err
}

var cfg = Config{
	InboundHeader:       "x-genai-api-key",
	OutboundHeader:      "x-litellm-api-key",
	LegacyPassthrough:   true,
	ResourceMetadataURL: "https://api.test/.well-known/oauth-protected-resource",
}

const v1 = "/v1/chat/completions"

func decide(h map[string]string, v Verifier, r KeyResolver) Decision {
	return Decide(context.Background(), cfg, v1, h, v, r)
}

func TestAgentKeyInTheInboundHeaderIsRenamedAndAuthorizationIsLeftAlone(t *testing.T) {
	// Claude Code with an Anthropic subscription: our key in the custom header,
	// Anthropic's OAuth in Authorization. LiteLLM forwards the latter upstream.
	for _, in := range []string{"sk-abc", "Bearer sk-abc"} {
		d := decide(map[string]string{"x-genai-api-key": in, "authorization": "Bearer sk-ant-oat01-xyz", "x-user-id": "spoof"}, fakeVerifier{}, &fakeResolver{})
		if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-abc" {
			t.Fatalf("%q: %+v", in, d)
		}
		if !contains(d.Remove, "x-genai-api-key") || !contains(d.Remove, "x-user-id") || contains(d.Remove, "authorization") {
			t.Fatalf("%q: remove=%v", in, d.Remove)
		}
	}
}

func TestUserJWTInTheInboundHeaderIsMappedAndAuthorizationIsLeftAlone(t *testing.T) {
	r := &fakeResolver{key: "sk-front"}
	d := decide(map[string]string{"x-genai-api-key": "Bearer eyJ.x.y", "authorization": "Bearer sk-ant-oat01-xyz"}, fakeVerifier{sub: "u@x.com", scopes: []string{"alitellm"}}, r)
	if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-front" || contains(d.Remove, "authorization") {
		t.Fatalf("user via custom header: %+v", d)
	}
}

func TestUserJWTInAuthorizationIsConsumed(t *testing.T) {
	r := &fakeResolver{key: "sk-front"}
	d := decide(map[string]string{"authorization": "Bearer eyJ.x.y"}, fakeVerifier{sub: "u@x.com", scopes: []string{"alitellm"}}, r)
	if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-front" || !contains(d.Remove, "authorization") {
		t.Fatalf("our JWT must not reach LiteLLM: %+v", d)
	}
}

func TestLegacyOutboundHeaderPassesThroughOnlyWhenEnabled(t *testing.T) {
	h := map[string]string{"x-litellm-api-key": "Bearer sk-old", "x-user-id": "spoof"}
	d := decide(h, fakeVerifier{}, &fakeResolver{})
	if !d.Allow || len(d.Set) != 0 || !contains(d.Remove, "x-user-id") {
		t.Fatalf("legacy: %+v", d)
	}
	off := cfg
	off.LegacyPassthrough = false
	if d := Decide(context.Background(), off, v1, h, fakeVerifier{}, &fakeResolver{}); d.Allow {
		t.Fatalf("legacy off: expected deny, got %+v", d)
	}
}

func TestALiteLLMKeyInAuthorizationPassesUntouchedWhileLegacyIsOn(t *testing.T) {
	// OpenAI SDK shape. LiteLLM accepts it natively; nothing to rename.
	for _, tok := range []string{"sk-abc", "sk-ant-oat01-xyz"} {
		d := decide(map[string]string{"authorization": "Bearer " + tok}, fakeVerifier{}, &fakeResolver{})
		if !d.Allow || len(d.Set) != 0 || contains(d.Remove, "authorization") {
			t.Fatalf("%s: %+v", tok, d)
		}
	}
	off := cfg
	off.LegacyPassthrough = false
	if d := Decide(context.Background(), off, "/v1/chat/completions", map[string]string{"authorization": "Bearer sk-abc"}, fakeVerifier{}, &fakeResolver{}); d.Allow || d.Status != 401 {
		t.Fatalf("legacy off: expected 401, got %+v", d)
	}
}

func TestMCPPathRequiresTheServiceScope(t *testing.T) {
	r := &fakeResolver{key: "sk-front"}
	v := fakeVerifier{sub: "u@x.com", scopes: []string{"alitellm", "mcp-google-drive"}}
	if d := Decide(context.Background(), cfg, "/mcp/mcp-google-drive", map[string]string{"authorization": "Bearer eyJ.x.y"}, v, r); !d.Allow {
		t.Fatalf("granted service: %+v", d)
	}
	r = &fakeResolver{key: "sk-front"}
	d := Decide(context.Background(), cfg, "/mcp/mcp-aws-eks-ro", map[string]string{"authorization": "Bearer eyJ.x.y"}, v, r)
	if d.Allow || d.Status != 403 {
		t.Fatalf("missing scope: %+v", d)
	}
	want := `Bearer error="insufficient_scope", scope="mcp-aws-eks-ro", resource_metadata="https://api.test/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro"`
	if d.WWWAuthenticate != want {
		t.Fatalf("challenge: %q", d.WWWAuthenticate)
	}
	if r.calls != 0 {
		t.Fatalf("no key lookup before the scope gate")
	}
}

func TestAgentKeysAreNotScopeGated(t *testing.T) {
	// Agents get their grant through the `authenticate` tool, as today.
	d := Decide(context.Background(), cfg, "/mcp/mcp-aws-eks-ro", map[string]string{"x-genai-api-key": "sk-agent"}, fakeVerifier{}, &fakeResolver{})
	if !d.Allow {
		t.Fatalf("agent on mcp: %+v", d)
	}
}

func TestInvalidJWTIs401WithAChallenge(t *testing.T) {
	d := decide(map[string]string{"authorization": "Bearer a.b.c"}, fakeVerifier{err: errors.New("bad sig")}, &fakeResolver{})
	if d.Allow || d.Status != 401 {
		t.Fatalf("invalid: %+v", d)
	}
	if d.WWWAuthenticate != `Bearer error="invalid_token", resource_metadata="https://api.test/.well-known/oauth-protected-resource"` {
		t.Fatalf("challenge: %q", d.WWWAuthenticate)
	}
}

func TestAnonymousIs401WithAChallenge(t *testing.T) {
	d := decide(map[string]string{}, fakeVerifier{}, &fakeResolver{})
	if d.Allow || d.Status != 401 {
		t.Fatalf("anon: %+v", d)
	}
	if d.WWWAuthenticate != `Bearer resource_metadata="https://api.test/.well-known/oauth-protected-resource"` {
		t.Fatalf("challenge: %q", d.WWWAuthenticate)
	}
}

func TestAnonymousOnAnMCPPathIsPointedAtOurDocumentForThatPath(t *testing.T) {
	d := Decide(context.Background(), cfg, "/mcp/mcp-aws-eks-ro", map[string]string{}, fakeVerifier{}, &fakeResolver{})
	want := `Bearer resource_metadata="https://api.test/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro"`
	if d.Status != 401 || d.WWWAuthenticate != want {
		t.Fatalf("mcp challenge: %+v", d)
	}
}

func TestChallengeDocNamesTheServiceRootNotTheDialledPath(t *testing.T) {
	want := "https://api.test/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro"
	for _, p := range []string{"/mcp/mcp-aws-eks-ro", "/mcp/mcp-aws-eks-ro/", "/mcp/mcp-aws-eks-ro/messages"} {
		if got := challengeDoc(cfg, p); got != want {
			t.Fatalf("%s: %q", p, got)
		}
	}
	if got := challengeDoc(cfg, v1); got != cfg.ResourceMetadataURL {
		t.Fatalf("non-mcp: %q", got)
	}
}

func TestAMalformedServiceSegmentIsNotAnMCPPath(t *testing.T) {
	// The segment lands in WWW-Authenticate and the JSON body unescaped, so
	// only a well-formed name is a service; anything else is not scope-gated
	// and LiteLLM 404s it.
	for _, p := range []string{"/mcp/", "/mcp//x", `/mcp/x"y`, "/mcp/x y"} {
		if svc := mcpService(p); svc != "" {
			t.Fatalf("%q: service %q", p, svc)
		}
		r := &fakeResolver{key: "sk-front"}
		d := Decide(context.Background(), cfg, p, map[string]string{"authorization": "Bearer eyJ.x.y"}, fakeVerifier{sub: "u@x.com"}, r)
		if !d.Allow || r.calls != 1 {
			t.Fatalf("%q: %+v calls=%d", p, d, r.calls)
		}
	}
}

func TestResolverFailureIs503NotA401(t *testing.T) {
	d := decide(map[string]string{"authorization": "Bearer a.b.c"}, fakeVerifier{sub: "u"}, &fakeResolver{err: errors.New("down")})
	if d.Allow || d.Status != 503 {
		t.Fatalf("resolver down: %+v", d)
	}
}

func contains(xs []string, x string) bool {
	for _, s := range xs {
		if s == x {
			return true
		}
	}
	return false
}
