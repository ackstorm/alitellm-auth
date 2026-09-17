package main

import (
	"context"
	"errors"
	"testing"

	authv3 "github.com/envoyproxy/go-control-plane/envoy/service/auth/v3"
	typev3 "github.com/envoyproxy/go-control-plane/envoy/type/v3"
)

func check(t *testing.T, s *Server, path string, headers map[string]string) *authv3.CheckResponse {
	t.Helper()
	req := &authv3.CheckRequest{Attributes: &authv3.AttributeContext{
		Request: &authv3.AttributeContext_Request{Http: &authv3.AttributeContext_HttpRequest{
			Method: "POST", Path: path, Headers: headers,
		}},
	}}
	resp, err := s.Check(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func TestCheckAllowMapsHeaderMutations(t *testing.T) {
	s := &Server{cfg: cfg, verifier: fakeVerifier{sub: "u"}, resolver: &fakeResolver{key: "sk-front"}}
	resp := check(t, s, "/v1/chat/completions?x=1", map[string]string{
		"authorization": "Bearer a.b.c", "x-user-id": "spoof",
	})
	ok := resp.GetOkResponse()
	if ok == nil {
		t.Fatalf("expected OK, got %+v", resp)
	}
	set := map[string]string{}
	for _, h := range ok.Headers {
		set[h.Header.Key] = h.Header.Value
	}
	if set["x-litellm-api-key"] != "Bearer sk-front" {
		t.Fatalf("headers: %v", set)
	}
	if !contains(ok.HeadersToRemove, "x-user-id") {
		t.Fatalf("remove: %v", ok.HeadersToRemove)
	}
}

func TestCheckDenyMapsStatusHeadersBodyAndStripsQueryFromDecisionPath(t *testing.T) {
	s := &Server{cfg: cfg, verifier: fakeVerifier{}, resolver: &fakeResolver{}}
	resp := check(t, s, "/mcp/mcp-aws-eks-ro?session=1", map[string]string{})
	denied := resp.GetDeniedResponse()
	if denied == nil || denied.Status.Code != typev3.StatusCode_Unauthorized {
		t.Fatalf("expected 401, got %+v", resp)
	}
	var wa, contentType string
	for _, h := range denied.Headers {
		switch h.Header.Key {
		case "www-authenticate":
			wa = h.Header.Value
		case "content-type":
			contentType = h.Header.Value
		}
	}
	want := `Bearer resource_metadata="https://api.test/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro"`
	if wa != want {
		t.Fatalf("www-authenticate: %q", wa)
	}
	if contentType != "application/json" || denied.Body != `{"error":"unauthorized","error_description":"present an API key or a bearer token"}` {
		t.Fatalf("denied response headers/body: %v / %q", denied.Headers, denied.Body)
	}
}

func TestCheckResolverFailureMapsTo503(t *testing.T) {
	s := &Server{cfg: cfg, verifier: fakeVerifier{sub: "u"}, resolver: &fakeResolver{err: errors.New("down")}}
	resp := check(t, s, "/v1/models", map[string]string{"authorization": "Bearer a.b.c"})
	denied := resp.GetDeniedResponse()
	if denied == nil || denied.Status.Code != typev3.StatusCode_ServiceUnavailable || denied.Body != `{"error":"key_resolver_unavailable"}` {
		t.Fatalf("expected 503 resolver response, got %+v", resp)
	}
}
