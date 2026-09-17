package main

import (
	"context"
	"errors"
	"testing"
)

type fakeVerifier struct {
	sub string
	err error
}

func (f fakeVerifier) Verify(_ string, _ string) (string, error) { return f.sub, f.err }

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
	ResourceBase:        "https://api.test",
	ResourceMetadataURL: "https://platform.test/.well-known/oauth-protected-resource",
}

const v1 = "/v1/chat/completions"

func decide(h map[string]string, v Verifier, r KeyResolver) Decision {
	return Decide(context.Background(), cfg, v1, h, v, r)
}

func TestAgentKeyIsRenamedAndNormalised(t *testing.T) {
	for _, in := range []string{"sk-abc", "Bearer sk-abc"} {
		d := decide(map[string]string{"x-genai-api-key": in, "x-user-id": "spoof"}, fakeVerifier{}, &fakeResolver{})
		if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-abc" {
			t.Fatalf("%q: %+v", in, d)
		}
		for _, h := range []string{"x-genai-api-key", "authorization", "x-user-id"} {
			if !contains(d.Remove, h) {
				t.Fatalf("%q: %s not removed", in, h)
			}
		}
	}
}

func TestAgentKeyWinsOverABearer(t *testing.T) {
	r := &fakeResolver{key: "sk-user"}
	d := decide(map[string]string{"x-genai-api-key": "sk-agent", "authorization": "Bearer a.b.c"}, fakeVerifier{sub: "u"}, r)
	if d.Set["x-litellm-api-key"] != "Bearer sk-agent" || r.calls != 0 {
		t.Fatalf("agent key must win without resolving: %+v calls=%d", d, r.calls)
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

func TestABearerThatIsNotAJWSIsALiteLLMKey(t *testing.T) {
	// The OpenAI SDK, LangChain and every curl example send the key this way.
	r := &fakeResolver{}
	d := decide(map[string]string{"authorization": "Bearer sk-abc"}, fakeVerifier{err: errors.New("not a jws")}, r)
	if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-abc" || r.calls != 0 {
		t.Fatalf("openai-sdk shape: %+v calls=%d", d, r.calls)
	}
	if !contains(d.Remove, "authorization") {
		t.Fatalf("the bearer must not reach LiteLLM twice: %+v", d)
	}
	off := cfg
	off.LegacyPassthrough = false
	if d := Decide(context.Background(), off, v1, map[string]string{"authorization": "Bearer sk-abc"}, fakeVerifier{}, r); d.Allow || d.Status != 401 {
		t.Fatalf("legacy off: expected 401, got %+v", d)
	}
}

func TestUserJWTIsMappedToTheFrontKeyAndKeepsAuthorization(t *testing.T) {
	r := &fakeResolver{key: "sk-front"}
	d := decide(map[string]string{"authorization": "Bearer eyJ.x.y"}, fakeVerifier{sub: "u@x.com"}, r)
	if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-front" {
		t.Fatalf("user: %+v", d)
	}
	if contains(d.Remove, "authorization") || !contains(d.Remove, "x-user-id") {
		t.Fatalf("user: authorization must stay, x-user-id must go: %+v", d)
	}
}

func TestInvalidJWTIs401WithAChallenge(t *testing.T) {
	d := decide(map[string]string{"authorization": "Bearer a.b.c"}, fakeVerifier{err: errors.New("bad sig")}, &fakeResolver{})
	if d.Allow || d.Status != 401 {
		t.Fatalf("invalid: %+v", d)
	}
	if d.WWWAuthenticate != `Bearer error="invalid_token", resource_metadata="https://platform.test/.well-known/oauth-protected-resource"` {
		t.Fatalf("challenge: %q", d.WWWAuthenticate)
	}
}

func TestAnonymousIs401WithAChallenge(t *testing.T) {
	d := decide(map[string]string{}, fakeVerifier{}, &fakeResolver{})
	if d.Allow || d.Status != 401 {
		t.Fatalf("anon: %+v", d)
	}
	if d.WWWAuthenticate != `Bearer resource_metadata="https://platform.test/.well-known/oauth-protected-resource"` {
		t.Fatalf("challenge: %q", d.WWWAuthenticate)
	}
}

func TestAnonymousOnAnMCPPathIsPointedAtThatServersDocument(t *testing.T) {
	d := Decide(context.Background(), cfg, "/mcp/mcp-aws-eks-ro", map[string]string{}, fakeVerifier{}, &fakeResolver{})
	want := `Bearer resource_metadata="https://api.test/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro"`
	if d.Status != 401 || d.WWWAuthenticate != want {
		t.Fatalf("mcp challenge: %+v", d)
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
