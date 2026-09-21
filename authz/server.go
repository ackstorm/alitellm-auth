package main

import (
	"context"
	"strings"

	corev3 "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	authv3 "github.com/envoyproxy/go-control-plane/envoy/service/auth/v3"
	typev3 "github.com/envoyproxy/go-control-plane/envoy/type/v3"
	"google.golang.org/genproto/googleapis/rpc/status"
	"google.golang.org/grpc/codes"
)

// Server adapts Decide to Envoy's ext_authz gRPC contract.
type Server struct {
	authv3.UnimplementedAuthorizationServer
	cfg      Config
	verifier Verifier
	resolver KeyResolver
}

func (s *Server) Check(ctx context.Context, req *authv3.CheckRequest) (*authv3.CheckResponse, error) {
	httpRequest := req.GetAttributes().GetRequest().GetHttp()
	path, _, _ := strings.Cut(httpRequest.GetPath(), "?")
	d := Decide(ctx, s.cfg, path, httpRequest.GetHeaders(), s.verifier, s.resolver)
	if d.Allow {
		set := make([]*corev3.HeaderValueOption, 0, len(d.Set))
		for key, value := range d.Set {
			set = append(set, &corev3.HeaderValueOption{
				Header:       &corev3.HeaderValue{Key: key, Value: value},
				AppendAction: corev3.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
			})
		}
		return &authv3.CheckResponse{
			Status: &status.Status{Code: int32(codes.OK)},
			HttpResponse: &authv3.CheckResponse_OkResponse{OkResponse: &authv3.OkHttpResponse{
				Headers: set, HeadersToRemove: d.Remove,
			}},
		}, nil
	}

	httpStatus := typev3.StatusCode_Unauthorized
	rpcStatus := codes.Unauthenticated
	if d.Status == 503 {
		httpStatus = typev3.StatusCode_ServiceUnavailable
		rpcStatus = codes.Unavailable
	} else if d.Status != 401 {
		httpStatus = typev3.StatusCode(d.Status)
	}
	deniedHeaders := []*corev3.HeaderValueOption{{
		Header: &corev3.HeaderValue{Key: "content-type", Value: "application/json"},
	}}
	if d.WWWAuthenticate != "" {
		deniedHeaders = append(deniedHeaders, &corev3.HeaderValueOption{
			Header: &corev3.HeaderValue{Key: "www-authenticate", Value: d.WWWAuthenticate},
		})
	}
	return &authv3.CheckResponse{
		Status: &status.Status{Code: int32(rpcStatus)},
		HttpResponse: &authv3.CheckResponse_DeniedResponse{DeniedResponse: &authv3.DeniedHttpResponse{
			Status:  &typev3.HttpStatus{Code: httpStatus},
			Headers: deniedHeaders,
			Body:    d.Body,
		}},
	}, nil
}
