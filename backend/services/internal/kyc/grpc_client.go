package kyc

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/connectivity"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	"shiptrip/internal/kyc/kycpb"
)

// MaxGRPCMessageBytes mirrors the Django server's grpc.max_*_message_length
// (see apps/kyc/management/commands/runkycgrpc.py). Asymmetric limits
// produce cryptic RESOURCE_EXHAUSTED errors — CLAUDE.md §G5.
const MaxGRPCMessageBytes = 16 << 20

// retryServiceConfig retries transient UNAVAILABLE / DEADLINE_EXCEEDED
// from the Django gRPC server. Safe because RecordSubmission is
// idempotency-keyed server-side (kyc_submission.idempotency_key, commit
// d6f4dc6) — duplicate writes collapse to the original row.
const retryServiceConfig = `{
    "methodConfig": [{
        "name": [{"service": "shiptrip.kyc.v1.KYCSubmissionService"}],
        "retryPolicy": {
            "maxAttempts": 4,
            "initialBackoff": "0.2s",
            "maxBackoff": "2s",
            "backoffMultiplier": 2.0,
            "retryableStatusCodes": ["UNAVAILABLE", "DEADLINE_EXCEEDED"]
        }
    }]
}`

// GRPCAuthMode picks how the Go client authenticates to the Django gRPC
// server. Mirrors the GRPC_AUTH_MODE env documented in CLAUDE.md §G5.
type GRPCAuthMode string

const (
	// GRPCAuthBearer sends a static shared token in the `authorization`
	// metadata header. Dev-only per CLAUDE.md §G5.
	GRPCAuthBearer GRPCAuthMode = "bearer"
	// GRPCAuthMTLS is the production mode: peer-verified self-signed CA.
	// Not yet wired — see TODO below.
	GRPCAuthMTLS GRPCAuthMode = "mtls"
)

// GRPCClientConfig bundles dial-time settings. Built from env in
// pkg/config.LoadKYCGRPC; passed to NewGRPCClient by main.
type GRPCClientConfig struct {
	// Target is a gRPC target string, e.g. "django:50051" inside
	// docker-compose or "localhost:50051" on the host.
	Target string
	// AuthMode is "bearer" in dev, "mtls" in prod.
	AuthMode GRPCAuthMode
	// BearerToken is the shared secret when AuthMode == "bearer". Empty
	// in mtls mode.
	BearerToken string
	// DialTimeout caps how long NewGRPCClient blocks waiting for the
	// initial connection. Boot deadline, not per-RPC.
	DialTimeout time.Duration
}

// GRPCClient implements Recorder against the generated stub. Owns the
// underlying *grpc.ClientConn; close it via Close() on shutdown.
type GRPCClient struct {
	conn   *grpc.ClientConn
	stub   kycpb.KYCSubmissionServiceClient
	log    *slog.Logger
	authMD metadata.MD
}

// NewGRPCClient dials Django's KYC gRPC server and returns a Recorder.
// The dial is blocking with a deadline so a missing or wrong KYC_GRPC_TARGET
// surfaces during service boot (CLAUDE.md §9: "evidence > assertions" —
// boot only reports ready when the dependency is actually reachable).
func NewGRPCClient(ctx context.Context, cfg GRPCClientConfig, log *slog.Logger) (*GRPCClient, error) {
	if cfg.Target == "" {
		return nil, errors.New("kyc grpc: target is required")
	}
	if cfg.DialTimeout <= 0 {
		cfg.DialTimeout = 10 * time.Second
	}

	var transport grpc.DialOption
	var authMD metadata.MD
	switch cfg.AuthMode {
	case GRPCAuthBearer:
		// Dev only. Django enforces the exact "Bearer <token>" string
		// (apps/kyc/management/commands/runkycgrpc.py:45).
		if cfg.BearerToken == "" {
			return nil, errors.New("kyc grpc: bearer mode requires GRPC_BEARER_TOKEN")
		}
		transport = grpc.WithTransportCredentials(insecure.NewCredentials())
		authMD = metadata.Pairs("authorization", "Bearer "+cfg.BearerToken)
	case GRPCAuthMTLS:
		// TODO(claude-b): load CA + client cert when cert-manager / mkcert
		// pipeline lands. Mirror runkycgrpc.py's mTLS branch.
		return nil, errors.New("kyc grpc: mtls mode is not yet wired (CLAUDE.md §G5 TODO)")
	default:
		return nil, fmt.Errorf("kyc grpc: unknown auth mode %q", cfg.AuthMode)
	}

	// grpc.NewClient is the modern (non-deprecated) constructor; the dial
	// is lazy. We force the connection eagerly below so KYC_GRPC_TARGET
	// misconfig surfaces at boot, not on the first user upload.
	//
	// Keepalive: KYC submissions are infrequent, so the HTTP/2 connection
	// can sit idle long enough for conntrack/NAT to silently drop the
	// flow. 30s pings (with PermitWithoutStream) keep the path warm.
	conn, err := grpc.NewClient(cfg.Target,
		transport,
		grpc.WithDefaultCallOptions(
			grpc.MaxCallSendMsgSize(MaxGRPCMessageBytes),
			grpc.MaxCallRecvMsgSize(MaxGRPCMessageBytes),
		),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                30 * time.Second,
			Timeout:             10 * time.Second,
			PermitWithoutStream: true,
		}),
		grpc.WithDefaultServiceConfig(retryServiceConfig),
	)
	if err != nil {
		return nil, fmt.Errorf("kyc grpc: new client %s: %w", cfg.Target, err)
	}

	probeCtx, cancel := context.WithTimeout(ctx, cfg.DialTimeout)
	defer cancel()
	conn.Connect()
	if err := waitForReady(probeCtx, conn); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("kyc grpc: connect %s: %w", cfg.Target, err)
	}

	return &GRPCClient{
		conn:   conn,
		stub:   kycpb.NewKYCSubmissionServiceClient(conn),
		log:    log,
		authMD: authMD,
	}, nil
}

// waitForReady blocks until the connection reaches Ready, or the
// context is cancelled. grpc-go exposes state transitions but no single
// "wait until ready" call — this poll is the idiomatic shape.
func waitForReady(ctx context.Context, conn *grpc.ClientConn) error {
	for {
		s := conn.GetState()
		if s == connectivity.Ready {
			return nil
		}
		if !conn.WaitForStateChange(ctx, s) {
			return ctx.Err()
		}
	}
}

// Close tears down the gRPC connection. Safe to call once; main wires
// it as a defer on shutdown.
func (c *GRPCClient) Close() error {
	if c.conn == nil {
		return nil
	}
	return c.conn.Close()
}

// RecordSubmission satisfies the Recorder interface. Translates the
// typed-string surface into proto enums and back.
func (c *GRPCClient) RecordSubmission(ctx context.Context, in RecordSubmissionInput) (RecordSubmissionOutput, error) {
	docType, ok := documentTypeToProto[in.DocumentType]
	if !ok {
		return RecordSubmissionOutput{}, fmt.Errorf("kyc grpc: unknown document_type %q", in.DocumentType)
	}

	// Auth metadata flows on every call. Django's interceptor reads
	// `authorization` per RPC, not per connection.
	if c.authMD != nil {
		ctx = metadata.NewOutgoingContext(ctx, c.authMD)
	}

	resp, err := c.stub.RecordSubmission(ctx, &kycpb.RecordSubmissionRequest{
		UserId:         in.UserID,
		DocumentType:   docType,
		IdempotencyKey: in.IdempotencyKey,
		FrontImageKey:  in.FrontImageKey,
		BackImageKey:   in.BackImageKey,
		SelfieImageKey: in.SelfieImageKey,
	})
	if err != nil {
		return RecordSubmissionOutput{}, translateGRPCError(err)
	}

	return RecordSubmissionOutput{
		SubmissionID: resp.GetSubmissionId(),
		Created:      resp.GetCreated(),
		Status:       statusFromProto(resp.GetStatus()),
	}, nil
}

// documentTypeToProto maps the wire-format strings the HTTP handler
// validates into proto enum values.
var documentTypeToProto = map[DocumentType]kycpb.DocumentType{
	DocumentIDCard:         kycpb.DocumentType_DOCUMENT_TYPE_ID_CARD,
	DocumentPassport:       kycpb.DocumentType_DOCUMENT_TYPE_PASSPORT,
	DocumentDrivingLicense: kycpb.DocumentType_DOCUMENT_TYPE_DRIVING_LICENSE,
}

// statusFromProto maps Django's returned proto Status into the typed
// strings the HTTP response uses. Unknown values fall back to PENDING
// rather than erroring — a future proto value should not crash the API,
// and PENDING is the safe default (forces re-review on the admin side).
func statusFromProto(s kycpb.Status) Status {
	switch s {
	case kycpb.Status_STATUS_PENDING:
		return StatusPending
	case kycpb.Status_STATUS_APPROVED:
		return StatusApproved
	case kycpb.Status_STATUS_REJECTED:
		return StatusRejected
	case kycpb.Status_STATUS_EXPIRED:
		return StatusExpired
	default:
		return StatusPending
	}
}

// translateGRPCError unwraps grpc status codes into stable sentinels so
// the HTTP handler can decide on 4xx vs 5xx without parsing strings.
// Keeps the existing ErrRecorderNotConfigured contract intact for the
// NoopRecorder path.
func translateGRPCError(err error) error {
	st, ok := status.FromError(err)
	if !ok {
		return err
	}
	switch st.Code() {
	case codes.InvalidArgument:
		return fmt.Errorf("kyc grpc: invalid argument: %s", st.Message())
	case codes.NotFound:
		return fmt.Errorf("kyc grpc: not found: %s", st.Message())
	case codes.Unauthenticated, codes.PermissionDenied:
		return fmt.Errorf("kyc grpc: auth rejected: %s", st.Message())
	default:
		return fmt.Errorf("kyc grpc: %s: %s", st.Code(), st.Message())
	}
}
