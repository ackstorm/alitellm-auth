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
	if cfg.IDPIssuer != "" && cfg.IDPAudience == "" {
		log.Fatal("AUTHZ_IDP_AUDIENCE is required when AUTHZ_IDP_ISSUER is set: an issuer trusted for any audience accepts tokens minted for other clients")
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// The front door mints `sub` as the email, so it verifies with the standard
	// subject; the IdP, if one is trusted, names its own claim.
	front, err := NewVerifier(ctx, cfg.Issuer, cfg.Audience, "")
	if err != nil {
		log.Fatalf("issuer: %v", err)
	}
	verifiers := map[string]Verifier{cfg.Issuer: front}
	if cfg.IDPIssuer != "" {
		idp, err := NewVerifier(ctx, cfg.IDPIssuer, cfg.IDPAudience, cfg.IDPSubjectClaim)
		if err != nil {
			log.Fatalf("idp issuer: %v", err)
		}
		verifiers[cfg.IDPIssuer] = idp
	}
	srv := &Server{
		cfg:      cfg,
		verifier: NewMultiVerifier(verifiers),
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
	log.Printf("authz listening on %s (inbound %v → outbound %s, issuer=%s, idp_issuer=%q)",
		cfg.ListenAddr, cfg.InboundHeaders, cfg.OutboundHeader, cfg.Issuer, cfg.IDPIssuer)
	if err := g.Serve(lis); err != nil {
		log.Fatal(err)
	}
}
