package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"
)

// cachedResolver asks the API for a user's front key and remembers it. A stale
// entry is served immediately and refreshed once in the background, so a TTL
// expiry is never on the request path — Envoy's ext_authz timeout is short.
// One mutex, one map, no eviction — entries are users, not requests.
type cachedResolver struct {
	url, token string
	ttl        time.Duration
	client     *http.Client
	mu         sync.Mutex
	cache      map[string]cacheEntry
	inflight   map[string]struct{}
}

type cacheEntry struct {
	key string
	exp time.Time
}

func NewResolver(resolverURL, token string, ttl time.Duration) KeyResolver {
	return &cachedResolver{url: resolverURL, token: token, ttl: ttl,
		client: &http.Client{Timeout: 3 * time.Second},
		cache:  map[string]cacheEntry{}, inflight: map[string]struct{}{}}
}

func (r *cachedResolver) KeyFor(ctx context.Context, sub string) (string, error) {
	r.mu.Lock()
	e, ok := r.cache[sub]
	if ok && time.Now().Before(e.exp) {
		r.mu.Unlock()
		return e.key, nil
	}
	if ok { // stale but usable: refresh off the request path, once
		if _, busy := r.inflight[sub]; !busy {
			r.inflight[sub] = struct{}{}
			go func() {
				_, _ = r.fetch(context.Background(), sub)
				r.mu.Lock()
				delete(r.inflight, sub)
				r.mu.Unlock()
			}()
		}
		r.mu.Unlock()
		return e.key, nil
	}
	r.mu.Unlock()
	return r.fetch(ctx, sub) // cold: the API mints under its own lock
}

func (r *cachedResolver) fetch(ctx context.Context, sub string) (string, error) {
	payload, _ := json.Marshal(map[string]string{"sub": sub})
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, r.url, bytes.NewReader(payload))
	req.Header.Set("content-type", "application/json")
	req.Header.Set("x-internal-token", r.token)
	resp, err := r.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("key resolver returned %d", resp.StatusCode)
	}
	var body struct {
		Key string `json:"key"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil || body.Key == "" {
		return "", fmt.Errorf("key resolver returned no key")
	}
	r.mu.Lock()
	r.cache[sub] = cacheEntry{key: body.Key, exp: time.Now().Add(r.ttl)}
	r.mu.Unlock()
	return body.Key, nil
}
