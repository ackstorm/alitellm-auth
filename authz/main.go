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
	if cfg.Issuer == "" || cfg.KeyResolverURL == "" || cfg.InternalToken == "" || cfg.ResourceMetadataURL == "" {
		log.Fatal("AUTHZ_ISSUER, AUTHZ_KEY_RESOLVER_URL, AUTHZ_INTERNAL_TOKEN and AUTHZ_RESOURCE_METADATA_URL are required")
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	verifier, err := NewVerifier(ctx, cfg.Issuer, cfg.Audience)
	if err != nil {
		log.Fatalf("issuer: %v", err)
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
	log.Printf("authz listening on %s (inbound %s → outbound %s, legacy=%v, issuer=%s)",
		cfg.ListenAddr, cfg.InboundHeader, cfg.OutboundHeader, cfg.LegacyPassthrough, cfg.Issuer)
	if err := g.Serve(lis); err != nil {
		log.Fatal(err)
	}
}
