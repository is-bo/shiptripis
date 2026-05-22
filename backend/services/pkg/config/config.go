// Package config loads service configuration from environment variables.
//
// The shared .env file (see CLAUDE.md §7b) is consumed by Django and
// every Go service, so loaders here MUST accept the variable names
// Django already uses — most importantly Postgres split vars
// (POSTGRES_HOST/USER/PASSWORD/...) rather than inventing a Go-only
// DATABASE_URL.
//
// Each loader returns a small typed struct that maps 1:1 onto a pkg's
// Config (db.Config, redisbus.Config, etc.). Services compose only
// the loaders they need — kyc doesn't need Redis, notif doesn't need
// S3, and so on.
//
// Loaders never read `.env` files themselves. docker-compose, systemd
// env-files, or direnv handle that. Double-loading silently overrides
// values and is a debugging nightmare.
package config

import (
	"errors"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
)

// errBuilder accumulates per-field errors during a load and joins them
// via errors.Join so callers retain structured errors.Is/errors.As
// behavior on individual problems while still seeing every gap on
// first boot.
type errBuilder struct{ errs []error }

func (b *errBuilder) addf(format string, args ...any) {
	b.errs = append(b.errs, fmt.Errorf(format, args...))
}

func (b *errBuilder) err() error {
	return errors.Join(b.errs...)
}

// ── primitives ───────────────────────────────────────────────────────────────

// mustString returns the value of name. If unset or empty, fall is
// returned when non-empty; otherwise the error builder is appended.
func mustString(b *errBuilder, name, fall string) string {
	v := strings.TrimSpace(os.Getenv(name))
	if v != "" {
		return v
	}
	if fall != "" {
		return fall
	}
	b.addf("%s is required", name)
	return ""
}

// optString returns the trimmed value or fall.
func optString(name, fall string) string {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return fall
	}
	return v
}

// optInt parses an int env var with a fallback. Invalid values are
// reported via the error builder.
func optInt(b *errBuilder, name string, fall int) int {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return fall
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		b.addf("%s must be int (got %q)", name, v)
		return fall
	}
	return n
}

// optBool parses a bool env var ("true"/"false"/"1"/"0"). Empty → fall.
func optBool(b *errBuilder, name string, fall bool) bool {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return fall
	}
	parsed, err := strconv.ParseBool(v)
	if err != nil {
		b.addf("%s must be a bool (got %q)", name, v)
		return fall
	}
	return parsed
}

// ── Postgres ─────────────────────────────────────────────────────────────────

// Postgres holds the connection URL plus pool sizing. URL is built from
// Django's split env vars if DATABASE_URL is not set, so a single
// .env file works for both runtimes.
type Postgres struct {
	URL      string
	MaxConns int32
}

// LoadPostgres reads either DATABASE_URL or Django's POSTGRES_* vars.
// maxConnsKey lets each service set its own per-service env var
// (e.g. CHAT_DB_MAX_CONNS=15) without colliding — the connection pool
// budget (CLAUDE.md §3) is load-bearing so callers MUST set this.
func LoadPostgres(maxConnsKey string, maxConnsDefault int32) (Postgres, error) {
	var b errBuilder

	rawURL := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if rawURL == "" {
		host := mustString(&b, "POSTGRES_HOST", "")
		port := optInt(&b, "POSTGRES_PORT", 5432)
		user := mustString(&b, "POSTGRES_USER", "")
		pass := mustString(&b, "POSTGRES_PASSWORD", "")
		name := mustString(&b, "POSTGRES_DB", "")
		if host != "" && user != "" && pass != "" && name != "" {
			u := url.URL{
				Scheme: "postgres",
				User:   url.UserPassword(user, pass),
				Host:   fmt.Sprintf("%s:%d", host, port),
				Path:   "/" + name,
			}
			rawURL = u.String()
		}
	} else if _, err := url.Parse(rawURL); err != nil {
		b.addf("DATABASE_URL is not parseable: %v", err)
	}

	maxConns := optInt(&b, maxConnsKey, int(maxConnsDefault))
	if maxConns <= 0 {
		b.addf("%s must be > 0 (got %d)", maxConnsKey, maxConns)
	}

	if err := b.err(); err != nil {
		return Postgres{}, err
	}
	return Postgres{URL: rawURL, MaxConns: int32(maxConns)}, nil
}

// ── Redis ────────────────────────────────────────────────────────────────────

type Redis struct {
	URL string
}

func LoadRedis() (Redis, error) {
	var b errBuilder
	u := mustString(&b, "REDIS_URL", "")
	if err := b.err(); err != nil {
		return Redis{}, err
	}
	return Redis{URL: u}, nil
}

// ── JWT ──────────────────────────────────────────────────────────────────────

type JWT struct {
	Secret string
}

func LoadJWT() (JWT, error) {
	var b errBuilder
	s := mustString(&b, "JWT_HS256_SECRET", "")
	if err := b.err(); err != nil {
		return JWT{}, err
	}
	return JWT{Secret: s}, nil
}

// ── S3 / object storage ──────────────────────────────────────────────────────

type S3 struct {
	Endpoint     string
	Region       string
	AccessKey    string
	SecretKey    string
	UsePathStyle bool
}

func LoadS3() (S3, error) {
	var b errBuilder
	endpoint := optString("S3_ENDPOINT_URL", "")
	region := optString("S3_REGION", "us-east-1")
	access := mustString(&b, "S3_ACCESS_KEY", "")
	secret := mustString(&b, "S3_SECRET_KEY", "")
	// Path-style defaults on when a custom endpoint is set (MinIO needs
	// it; most S3-compat providers accept it). Set S3_USE_PATH_STYLE
	// explicitly to override — e.g. real AWS S3 or a virtual-host-only
	// provider.
	pathStyle := optBool(&b, "S3_USE_PATH_STYLE", endpoint != "")
	if err := b.err(); err != nil {
		return S3{}, err
	}
	return S3{
		Endpoint:     endpoint,
		Region:       region,
		AccessKey:    access,
		SecretKey:    secret,
		UsePathStyle: pathStyle,
	}, nil
}

// ── KYC gRPC client ──────────────────────────────────────────────────────────

// KYCGRPC holds the kyc-service → Django gRPC dial settings. Matches
// the env contract documented in CLAUDE.md §G5 and the Django runner
// command (apps/kyc/management/commands/runkycgrpc.py).
type KYCGRPC struct {
	Target      string
	AuthMode    string
	BearerToken string
}

// LoadKYCGRPC reads KYC_GRPC_TARGET + GRPC_AUTH_MODE + GRPC_BEARER_TOKEN.
// Target is required — a half-built deploy without the gRPC dependency
// should fail loud at boot rather than ship a NoopRecorder to prod
// (CLAUDE.md §9). GRPC_AUTH_MODE defaults to "mtls" per §G5 so a missing
// value in prod surfaces as a startup error (mtls is not yet wired)
// rather than silently downgrading to bearer.
func LoadKYCGRPC() (KYCGRPC, error) {
	var b errBuilder
	target := mustString(&b, "KYC_GRPC_TARGET", "")
	mode := strings.ToLower(optString("GRPC_AUTH_MODE", "mtls"))
	switch mode {
	case "bearer", "mtls":
		// ok
	default:
		b.addf("GRPC_AUTH_MODE must be 'bearer' or 'mtls' (got %q)", mode)
	}
	token := optString("GRPC_BEARER_TOKEN", "")
	if mode == "bearer" && token == "" {
		b.addf("GRPC_BEARER_TOKEN is required when GRPC_AUTH_MODE=bearer")
	}
	if err := b.err(); err != nil {
		return KYCGRPC{}, err
	}
	return KYCGRPC{Target: target, AuthMode: mode, BearerToken: token}, nil
}

// ── FCM (push fallback) ──────────────────────────────────────────────────────

// FCM holds the notif-service push-fallback settings. CLAUDE.md §G1 path:
// stream → wait 2s → check delivered:<event_id> → send via FCM if absent.
//
// Disabled by default — V1 ships without the schema (no fcm_token column
// on accounts_user) and without the Django publisher writing to the
// stream. The consumer is built ahead so flipping FCM_ENABLED=true once
// both sides land is a one-knob change, not a feature build.
type FCM struct {
	Enabled         bool
	Stream          string
	ConsumerGroup   string
	ConsumerName    string
	ProjectID       string // Firebase project — required when Enabled.
	CredentialsPath string // Service-account JSON path — required when Enabled.
}

// LoadFCM reads FCM_* env vars. When FCM_ENABLED is false (the default)
// every other field is optional and the returned struct can be passed
// to the consumer for a no-op idle state. When true, ProjectID and
// CredentialsPath are required so a half-configured push deploy fails
// loud at boot per CLAUDE.md §9.
func LoadFCM() (FCM, error) {
	var b errBuilder
	enabled := optBool(&b, "FCM_ENABLED", false)
	stream := optString("FCM_STREAM", "notif:fcm")
	group := optString("FCM_CONSUMER_GROUP", "notif-fcm-workers")
	// The consumer name disambiguates pods inside the group. HOSTNAME is
	// set by K3s to the pod name; fall back to a literal so dev still works.
	name := optString("FCM_CONSUMER_NAME", optString("HOSTNAME", "notif-fcm-1"))

	project := optString("FCM_PROJECT_ID", "")
	creds := optString("FCM_CREDENTIALS_PATH", "")
	if enabled {
		if project == "" {
			b.addf("FCM_PROJECT_ID is required when FCM_ENABLED=true")
		}
		if creds == "" {
			b.addf("FCM_CREDENTIALS_PATH is required when FCM_ENABLED=true")
		}
	}
	if err := b.err(); err != nil {
		return FCM{}, err
	}
	return FCM{
		Enabled:         enabled,
		Stream:          stream,
		ConsumerGroup:   group,
		ConsumerName:    name,
		ProjectID:       project,
		CredentialsPath: creds,
	}, nil
}

// ── logger / service identity ────────────────────────────────────────────────

type Logger struct {
	Service string
	Level   string
}

// LoadLogger returns logger config. The service name is fixed per
// binary (each main.go knows what it is), so it's not read from env;
// LOG_LEVEL is the only runtime knob.
func LoadLogger(service string) Logger {
	if service == "" {
		// Empty service name is a programming error, not a config error.
		// The logger pkg will fall back to "service": "" — visible enough.
		service = "unknown"
	}
	return Logger{
		Service: service,
		Level:   optString("LOG_LEVEL", "info"),
	}
}

// ── HTTP listen address ──────────────────────────────────────────────────────

// HTTPAddr reads an addr env var with a sensible fallback. Each service
// uses its own var (CHAT_HTTP_ADDR, NOTIF_HTTP_ADDR, KYC_HTTP_ADDR) so
// they can run side-by-side in dev.
func HTTPAddr(envKey, fallback string) string {
	return optString(envKey, fallback)
}

// String reads an arbitrary string env var with a fallback. Use for
// non-addr config (bucket names, mode flags, etc).
func String(envKey, fallback string) string {
	return optString(envKey, fallback)
}
