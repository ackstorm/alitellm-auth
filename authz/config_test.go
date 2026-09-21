package main

import (
	"reflect"
	"testing"
)

func TestLoadConfigParsesInboundHeaders(t *testing.T) {
	t.Setenv("AUTHZ_INBOUND_HEADERS", " X-GenAI-Api-Key , x-api-key,, x-custom ")
	got := LoadConfig().InboundHeaders
	want := []string{"x-genai-api-key", "x-api-key", "x-custom"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	t.Setenv("AUTHZ_INBOUND_HEADERS", "")
	if got := LoadConfig().InboundHeaders; !reflect.DeepEqual(got, []string{"x-genai-api-key", "x-api-key"}) {
		t.Fatalf("default: %v", got)
	}
}
