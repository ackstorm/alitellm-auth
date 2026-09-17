package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func keyServer(t *testing.T, calls *int32, fail func(n int32) bool) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(calls, 1)
		if r.Method != http.MethodPost || r.Header.Get("x-internal-token") != "shh" {
			w.WriteHeader(403)
			return
		}
		if fail != nil && fail(n) {
			w.WriteHeader(502)
			return
		}
		var body struct{ Sub string }
		json.NewDecoder(r.Body).Decode(&body)
		json.NewEncoder(w).Encode(map[string]string{"key": "sk-" + body.Sub})
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestResolverCachesPerSubAndPostsTheSubject(t *testing.T) {
	var calls int32
	r := NewResolver(keyServer(t, &calls, nil).URL, "shh", time.Minute)
	for i := 0; i < 3; i++ {
		if k, err := r.KeyFor(context.Background(), "u@x.com"); err != nil || k != "sk-u@x.com" {
			t.Fatalf("k=%q err=%v", k, err)
		}
	}
	if _, err := r.KeyFor(context.Background(), "v@x.com"); err != nil {
		t.Fatal(err)
	}
	if calls != 2 {
		t.Fatalf("expected 2 upstream calls, got %d", calls)
	}
}

func TestResolverErrorsAreNotCached(t *testing.T) {
	var calls int32
	r := NewResolver(keyServer(t, &calls, func(n int32) bool { return n == 1 }).URL, "shh", time.Minute)
	if _, err := r.KeyFor(context.Background(), "u"); err == nil {
		t.Fatal("expected error on 502")
	}
	if k, err := r.KeyFor(context.Background(), "u"); err != nil || k != "sk-u" {
		t.Fatalf("retry: k=%q err=%v", k, err)
	}
}

func TestAStaleEntryIsServedAndRefreshedOffTheRequestPath(t *testing.T) {
	var calls int32
	r := NewResolver(keyServer(t, &calls, nil).URL, "shh", time.Millisecond)
	if _, err := r.KeyFor(context.Background(), "u"); err != nil {
		t.Fatal(err)
	}
	time.Sleep(5 * time.Millisecond) // now stale
	start := time.Now()
	k, err := r.KeyFor(context.Background(), "u")
	if err != nil || k != "sk-u" {
		t.Fatalf("stale serve: k=%q err=%v", k, err)
	}
	if time.Since(start) > 50*time.Millisecond {
		t.Fatalf("stale serve waited on the network: %v", time.Since(start))
	}
	// bounded wait for the background refresh — never an unbounded loop
	for i := 0; i < 50 && atomic.LoadInt32(&calls) < 2; i++ {
		time.Sleep(10 * time.Millisecond)
	}
	if atomic.LoadInt32(&calls) != 2 {
		t.Fatalf("expected one background refresh, saw %d calls", calls)
	}
}
