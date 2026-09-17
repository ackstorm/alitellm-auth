package main

import (
	"context"
	"log"
	"net"
	"os/signal"
	"syscall"

	authv3 "github.com/envoyproxy/go-control-plane/envoy/service/auth/v3"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
)

func main() {
	cfg := LoadConfig()
	if len(cfg.Issuers) == 0 || cfg.KeyResolverURL == "" || cfg.InternalToken == "" ||
		cfg.ResourceMetadataURL == "" || cfg.ResourceBase == "" {
		log.Fatal("AUTHZ_ISSUERS, AUTHZ_KEY_RESOLVER_URL, AUTHZ_INTERNAL_TOKEN, AUTHZ_RESOURCE_METADATA_URL and AUTHZ_RESOURCE_BASE are required")
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	verifier, err := NewVerifier(ctx, cfg.Issuers, cfg.Audience, cfg.ResourceBase)
	if err != nil {
		log.Fatalf("issuers: %v", err)
	}
	srv := &Server{
		cfg:      cfg,
		verifier: verifier,
		resolver: NewResolver(cfg.KeyResolverURL, cfg.InternalToken, cfg.KeyCacheTTL),
	}
	lis, err := net.Listen("tcp", cfg.ListenAddr)
	if err != nil {
		log.Fatal(err)
	}

	g := grpc.NewServer()
	authv3.RegisterAuthorizationServer(g, srv)
	healthServer := health.NewServer()
	healthServer.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)
	healthpb.RegisterHealthServer(g, healthServer)
	go func() {
		<-ctx.Done()
		healthServer.SetServingStatus("", healthpb.HealthCheckResponse_NOT_SERVING)
		g.GracefulStop()
	}()
	log.Printf("authz listening on %s (inbound %s → outbound %s, legacy=%v, issuers=%v)",
		cfg.ListenAddr, cfg.InboundHeader, cfg.OutboundHeader, cfg.LegacyPassthrough, cfg.Issuers)
	if err := g.Serve(lis); err != nil {
		log.Fatal(err)
	}
}
