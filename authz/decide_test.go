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
	InboundHeaders:      []string{"x-genai-api-key", "x-api-key"},
	OutboundHeader:      "x-litellm-api-key",
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

func TestXAPIKeyIsASecondInboundHeader(t *testing.T) {
	// Claude Code with ANTHROPIC_API_KEY, or an apiKeyHelper printing a front
	// token: the Anthropic SDK sends x-api-key, never Authorization.
	d := decide(map[string]string{"x-api-key": "sk-abc"}, fakeVerifier{}, &fakeResolver{})
	if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-abc" || !contains(d.Remove, "x-api-key") {
		t.Fatalf("key via x-api-key: %+v", d)
	}
	r := &fakeResolver{key: "sk-front"}
	d = decide(map[string]string{"x-api-key": "eyJ.x.y"}, fakeVerifier{sub: "u@x.com", scopes: []string{"alitellm"}}, r)
	if !d.Allow || d.Set["x-litellm-api-key"] != "Bearer sk-front" || !contains(d.Remove, "x-api-key") {
		t.Fatalf("jwt via x-api-key: %+v", d)
	}
	// The custom header wins when both are present.
	d = decide(map[string]string{"x-genai-api-key": "sk-custom", "x-api-key": "sk-anthropic"}, fakeVerifier{}, &fakeResolver{})
	if d.Set["x-litellm-api-key"] != "Bearer sk-custom" {
		t.Fatalf("precedence: %+v", d)
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

func TestOutboundHeaderPassesThroughUntouched(t *testing.T) {
	// A LiteLLM key already in LiteLLM's own header: LiteLLM authenticates it.
	h := map[string]string{"x-litellm-api-key": "Bearer sk-old", "x-user-id": "spoof"}
	d := decide(h, fakeVerifier{}, &fakeResolver{})
	if !d.Allow || len(d.Set) != 0 || !contains(d.Remove, "x-user-id") || contains(d.Remove, "x-litellm-api-key") {
		t.Fatalf("outbound header: %+v", d)
	}
}

func TestAForeignAuthorizationIsForwardedUntouchedOnEveryPath(t *testing.T) {
	// Not ours: a LiteLLM key in the OpenAI-SDK shape, Anthropic's OAuth, LiteLLM
	// UI's own bearer on /v1/agents or /key/info, a Basic credential. LiteLLM decides.
	for _, path := range []string{v1, "/v1/agents", "/key/info", "/health/license", "/mcp/mcp-aws-eks-ro"} {
		for _, auth := range []string{"Bearer sk-abc", "Bearer sk-ant-oat01-xyz", "Bearer opaque-session-token", "Basic dXNlcjpwdw=="} {
			r := &fakeResolver{}
			d := Decide(context.Background(), cfg, path, map[string]string{"authorization": auth, "x-user-id": "spoof"}, fakeVerifier{err: errors.New("never called")}, r)
			if !d.Allow || len(d.Set) != 0 || contains(d.Remove, "authorization") || !contains(d.Remove, "x-user-id") {
				t.Fatalf("%s %q: %+v", path, auth, d)
			}
			if r.calls != 0 {
				t.Fatalf("%s %q: resolver called for a foreign credential", path, auth)
			}
		}
	}
}

func TestAnonymousOnTheCatchAllIsForwardedUntouched(t *testing.T) {
	// LiteLLM's UI, its health and admin surfaces: nothing presented is not our
	// business outside the protected families.
	for _, path := range []string{"/", "/ui", "/ui/", "/health/license", "/key/info", "/sso/callback", "/v2/models", "/v1beta"} {
		d := Decide(context.Background(), cfg, path, map[string]string{"x-user-id": "spoof"}, fakeVerifier{}, &fakeResolver{})
		if !d.Allow || len(d.Set) != 0 || !contains(d.Remove, "x-user-id") {
			t.Fatalf("%s: %+v", path, d)
		}
	}
}

func TestProtectedFamiliesRequireACredential(t *testing.T) {
	for _, path := range []string{"/v1", "/v1/", "/v1/chat/completions", "/gemini/v1beta/models", "/mcp/mcp-aws-eks-ro", "/a2a/agent"} {
		d := Decide(context.Background(), cfg, path, map[string]string{}, fakeVerifier{}, &fakeResolver{})
		if d.Allow || d.Status != 401 || d.WWWAuthenticate == "" {
			t.Fatalf("%s: %+v", path, d)
		}
	}
	for _, path := range []string{"/v10/x", "/gemini-ui", "/mcpx", "/a2ab"} {
		if protected(path) {
			t.Fatalf("%s must not be protected", path)
		}
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
	if d.Body != `{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in x-genai-api-key, x-api-key or Authorization: Bearer"}` {
		t.Fatalf("body: %s", d.Body)
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

func TestOnlyDeclaredInboundHeadersAreSlots(t *testing.T) {
	// A deployment that declares one slot: x-api-key is then just another
	// header, so a key there is "nothing presented" — 401 on /v1, forwarded
	// untouched on the catch-all.
	one := cfg
	one.InboundHeaders = []string{"x-genai-api-key"}
	h := map[string]string{"x-api-key": "sk-abc"}
	if d := Decide(context.Background(), one, v1, h, fakeVerifier{}, &fakeResolver{}); d.Allow || d.Status != 401 {
		t.Fatalf("undeclared slot on /v1: %+v", d)
	}
	if d := Decide(context.Background(), one, "/health/license", h, fakeVerifier{}, &fakeResolver{}); !d.Allow || len(d.Set) != 0 || contains(d.Remove, "x-api-key") {
		t.Fatalf("undeclared slot on the catch-all: %+v", d)
	}
	if d := Decide(context.Background(), one, v1, map[string]string{}, fakeVerifier{}, &fakeResolver{}); d.Body != `{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in x-genai-api-key or Authorization: Bearer"}` {
		t.Fatalf("body names only the declared slots: %s", d.Body)
	}
}

func TestInboundHeaderPrecedenceFollowsTheList(t *testing.T) {
	rev := cfg
	rev.InboundHeaders = []string{"x-api-key", "x-genai-api-key"}
	d := Decide(context.Background(), rev, v1, map[string]string{"x-genai-api-key": "sk-custom", "x-api-key": "sk-anthropic"}, fakeVerifier{}, &fakeResolver{})
	if d.Set["x-litellm-api-key"] != "Bearer sk-anthropic" || !contains(d.Remove, "x-api-key") || contains(d.Remove, "x-genai-api-key") {
		t.Fatalf("precedence: %+v", d)
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
