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
// the loaders they need — KYC uses Redis for distributed upload abuse
// protection, while notification still doesn't need S3, and so on.
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
	"time"
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
	} else if parsed, err := url.Parse(rawURL); err != nil {
		// Do not echo parser errors: they can include the credential-bearing URL.
		b.addf("DATABASE_URL is not parseable")
	} else if parsed.Scheme != "postgres" && parsed.Scheme != "postgresql" {
		b.addf("DATABASE_URL must use postgres or postgresql scheme")
	} else if parsed.Hostname() == "" || strings.TrimPrefix(parsed.Path, "/") == "" {
		b.addf("DATABASE_URL must include a host and database name")
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
	if u != "" {
		parsed, err := url.Parse(u)
		if err != nil || (parsed.Scheme != "redis" && parsed.Scheme != "rediss") || parsed.Hostname() == "" {
			b.addf("REDIS_URL must be a redis:// or rediss:// URL with a host")
		}
	}
	if err := b.err(); err != nil {
		return Redis{}, err
	}
	return Redis{URL: u}, nil
}

// KYCUploadRateLimit holds the distributed upload budgets consumed by the Go
// KYC service. Defaults allow legitimate document retries while bounding the
// number of multipart bodies and object writes one account or source address
// can attempt in an hour.
type KYCUploadRateLimit struct {
	UserLimit      int64
	UserWindow     time.Duration
	IPLimit        int64
	IPWindow       time.Duration
	ClientIPSource string
}

func LoadKYCUploadRateLimit() (KYCUploadRateLimit, error) {
	var b errBuilder
	userLimit := optInt(&b, "KYC_UPLOAD_USER_LIMIT", 6)
	userWindowSeconds := optInt(&b, "KYC_UPLOAD_USER_WINDOW_SECONDS", 3600)
	ipLimit := optInt(&b, "KYC_UPLOAD_IP_LIMIT", 0)
	ipWindowSeconds := optInt(&b, "KYC_UPLOAD_IP_WINDOW_SECONDS", 0)
	clientIPSource := strings.ToLower(optString("KYC_UPLOAD_CLIENT_IP_SOURCE", ""))

	if userLimit <= 0 {
		b.addf("KYC_UPLOAD_USER_LIMIT must be > 0 (got %d)", userLimit)
	}
	if userWindowSeconds < 60 || userWindowSeconds > 86400 {
		b.addf("KYC_UPLOAD_USER_WINDOW_SECONDS must be between 60 and 86400 (got %d)", userWindowSeconds)
	}
	if ipLimit < 0 {
		b.addf("KYC_UPLOAD_IP_LIMIT must be >= 0 (got %d)", ipLimit)
	}
	if ipLimit == 0 {
		if ipWindowSeconds != 0 {
			b.addf("KYC_UPLOAD_IP_WINDOW_SECONDS must be 0 when KYC_UPLOAD_IP_LIMIT is 0")
		}
		if clientIPSource != "" {
			b.addf("KYC_UPLOAD_CLIENT_IP_SOURCE must be empty when KYC_UPLOAD_IP_LIMIT is 0")
		}
	} else if ipWindowSeconds < 60 || ipWindowSeconds > 86400 {
		b.addf("KYC_UPLOAD_IP_WINDOW_SECONDS must be between 60 and 86400 (got %d)", ipWindowSeconds)
	} else if clientIPSource != "remote" && clientIPSource != "x-real-ip" && clientIPSource != "x-forwarded-for" {
		b.addf("KYC_UPLOAD_CLIENT_IP_SOURCE must be remote, x-real-ip, or x-forwarded-for when the IP budget is enabled")
	}
	if err := b.err(); err != nil {
		return KYCUploadRateLimit{}, err
	}
	return KYCUploadRateLimit{
		UserLimit:      int64(userLimit),
		UserWindow:     time.Duration(userWindowSeconds) * time.Second,
		IPLimit:        int64(ipLimit),
		IPWindow:       time.Duration(ipWindowSeconds) * time.Second,
		ClientIPSource: clientIPSource,
	}, nil
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

	// TLS cert paths, used only when AuthMode == "mtls". The Go client
	// presents ClientCert/ClientKey and verifies the Django server's cert
	// against CACert (the shared self-signed CA per §G5). Empty in bearer
	// mode.
	CACert     string
	ClientCert string
	ClientKey  string
}

// LoadKYCGRPC reads KYC_GRPC_TARGET + GRPC_AUTH_MODE and the auth-mode
// specific vars: GRPC_BEARER_TOKEN in bearer mode, or the
// GRPC_TLS_CA_CERT/GRPC_TLS_CLIENT_CERT/GRPC_TLS_CLIENT_KEY trio in mtls
// mode. Target is required — a half-built deploy without the gRPC
// dependency should fail loud at boot rather than ship a NoopRecorder to
// prod (CLAUDE.md §9). GRPC_AUTH_MODE defaults to "mtls" per §G5 so a
// missing value in prod surfaces as a config error (missing certs)
// rather than silently downgrading to bearer. The Go client side of mtls
// is wired (grpc_client.go); the Django server branch + cert pipeline are
// still TODO (see HANDOVER.md).
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

	caCert := optString("GRPC_TLS_CA_CERT", "")
	clientCert := optString("GRPC_TLS_CLIENT_CERT", "")
	clientKey := optString("GRPC_TLS_CLIENT_KEY", "")
	if mode == "mtls" {
		// All three are mandatory in mtls mode — a half-configured TLS
		// deploy must fail loud at boot, not silently fall back (§9, §G5).
		if caCert == "" {
			b.addf("GRPC_TLS_CA_CERT is required when GRPC_AUTH_MODE=mtls")
		}
		if clientCert == "" {
			b.addf("GRPC_TLS_CLIENT_CERT is required when GRPC_AUTH_MODE=mtls")
		}
		if clientKey == "" {
			b.addf("GRPC_TLS_CLIENT_KEY is required when GRPC_AUTH_MODE=mtls")
		}
	}

	if err := b.err(); err != nil {
		return KYCGRPC{}, err
	}
	return KYCGRPC{
		Target:      target,
		AuthMode:    mode,
		BearerToken: token,
		CACert:      caCert,
		ClientCert:  clientCert,
		ClientKey:   clientKey,
	}, nil
}

// ── FCM (push fallback) ──────────────────────────────────────────────────────

// FCM holds the notif-service push-fallback settings. CLAUDE.md §G1 path:
// stream → wait 2s → check delivered:<event_id>:<user_id> → send via FCM
// if absent. Disabled by default; activation additionally requires valid
// Firebase Admin credentials and matching mobile client configuration.
type FCM struct {
	Enabled         bool
	Stream          string
	ResultsStream   string
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
	resultsStream := optString("FCM_RESULTS_STREAM", "notif:fcm:results")
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
		ResultsStream:   resultsStream,
		ConsumerGroup:   group,
		ConsumerName:    name,
		ProjectID:       project,
		CredentialsPath: creds,
	}, nil
}

// ── Email (SMTP transactional sender) ────────────────────────────────────────

// Email holds the email-service settings. Django XADDs rendered messages onto
// the `email:send` stream; the consumer sends them over SMTP.
//
// Disabled by default. Flipping EMAIL_ENABLED=true activates ordinary
// non-secret stream delivery once the SMTP environment is complete.
type Email struct {
	// Provider is a transport label used for health/metrics and configuration
	// review. Sender.net uses the same standards-compliant SMTP seam as any
	// other relay; the Go worker deliberately does not couple to a vendor SDK.
	Provider      string
	Enabled       bool
	Stream        string
	ConsumerGroup string
	ConsumerName  string

	SMTPHost     string // required when Enabled
	SMTPPort     int    // required when Enabled
	SMTPUsername string // optional (dev sinks like MailHog need no auth)
	SMTPPassword string
	FromAddr     string // required when Enabled
	FromName     string // optional display name
	UseTLS       bool   // STARTTLS (587) / implicit TLS (465); false for dev (25/1025)
}

// LoadEmail reads EMAIL_* env vars. When EMAIL_ENABLED is false (the default)
// every other field is optional and the struct can be passed to the consumer
// for a no-op idle state. When true, SMTP host/port + from address are required
// so a half-configured mail deploy fails loud at boot per CLAUDE.md §9.
func LoadEmail() (Email, error) {
	var b errBuilder
	enabled := optBool(&b, "EMAIL_ENABLED", false)
	provider := strings.ToLower(optString("EMAIL_PROVIDER", "smtp"))
	switch provider {
	case "smtp", "sender_net", "sender.net":
		// Sender.net is an SMTP relay adapter, not a separate delivery path.
		if provider == "sender.net" {
			provider = "sender_net"
		}
	default:
		b.addf("EMAIL_PROVIDER must be 'smtp' or 'sender_net' (got %q)", provider)
	}
	stream := optString("EMAIL_STREAM", "email:send")
	group := optString("EMAIL_CONSUMER_GROUP", "email-send-workers")
	name := optString("EMAIL_CONSUMER_NAME", optString("HOSTNAME", "email-1"))

	host := optString("EMAIL_SMTP_HOST", "")
	port := optInt(&b, "EMAIL_SMTP_PORT", 0)
	user := optString("EMAIL_SMTP_USERNAME", "")
	pass := optString("EMAIL_SMTP_PASSWORD", "")
	from := optString("EMAIL_FROM_ADDR", "")
	fromName := optString("EMAIL_FROM_NAME", "")
	useTLS := optBool(&b, "EMAIL_USE_TLS", true)

	if enabled {
		if host == "" {
			b.addf("EMAIL_SMTP_HOST is required when EMAIL_ENABLED=true")
		}
		if port == 0 {
			b.addf("EMAIL_SMTP_PORT is required when EMAIL_ENABLED=true")
		}
		if from == "" {
			b.addf("EMAIL_FROM_ADDR is required when EMAIL_ENABLED=true")
		}
		if provider == "sender_net" {
			if user == "" {
				b.addf("EMAIL_SMTP_USERNAME is required for Sender.net")
			}
			if pass == "" {
				b.addf("EMAIL_SMTP_PASSWORD is required for Sender.net")
			}
			if !useTLS {
				b.addf("EMAIL_USE_TLS must be true for Sender.net")
			}
		}
	}
	if err := b.err(); err != nil {
		return Email{}, err
	}
	return Email{
		Provider:      provider,
		Enabled:       enabled,
		Stream:        stream,
		ConsumerGroup: group,
		ConsumerName:  name,
		SMTPHost:      host,
		SMTPPort:      port,
		SMTPUsername:  user,
		SMTPPassword:  pass,
		FromAddr:      from,
		FromName:      fromName,
		UseTLS:        useTLS,
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

// HTTPAddr reads a service-specific address, then Railway's injected PORT,
// then the local fallback. Compose sets the service-specific values so the
// binaries can run side-by-side on a developer machine.
func HTTPAddr(envKey, fallback string) string {
	if addr := optString(envKey, ""); addr != "" {
		return addr
	}
	if port := optString("PORT", ""); port != "" {
		return ":" + port
	}
	return fallback
}

// String reads an arbitrary string env var with a fallback. Use for
// non-addr config (bucket names, mode flags, etc).
func String(envKey, fallback string) string {
	return optString(envKey, fallback)
}
