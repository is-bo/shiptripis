package config

import (
	"net/url"
	"strings"
	"testing"
)

// clearConfigEnv blanks every env var the loaders read so a test starts from a
// known-empty environment. t.Setenv registers cleanup, so values set here are
// restored after the test; we set them to "" rather than unset because Go's
// testing has no per-test Unsetenv with auto-restore. The loaders treat "" the
// same as unset (mustString/optString both TrimSpace then check empty).
func clearConfigEnv(t *testing.T) {
	t.Helper()
	for _, k := range []string{
		"DATABASE_URL", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER",
		"POSTGRES_PASSWORD", "POSTGRES_DB",
		"REDIS_URL", "JWT_HS256_SECRET",
		"S3_ENDPOINT_URL", "S3_REGION", "S3_ACCESS_KEY", "S3_SECRET_KEY",
		"S3_USE_PATH_STYLE",
		"KYC_GRPC_TARGET", "GRPC_AUTH_MODE", "GRPC_BEARER_TOKEN",
		"FCM_ENABLED", "FCM_STREAM", "FCM_CONSUMER_GROUP", "FCM_CONSUMER_NAME",
		"FCM_PROJECT_ID", "FCM_CREDENTIALS_PATH", "HOSTNAME",
		"LOG_LEVEL", "CHAT_DB_MAX_CONNS",
	} {
		t.Setenv(k, "")
	}
}

// ── Postgres ───────────────────────────────────────────────────────────────

func TestLoadPostgres_BuildsURLFromSplitVars(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("POSTGRES_HOST", "db")
	t.Setenv("POSTGRES_PORT", "5433")
	t.Setenv("POSTGRES_USER", "shiptrip")
	t.Setenv("POSTGRES_PASSWORD", "p@ss word") // exercises url-encoding
	t.Setenv("POSTGRES_DB", "shiptrip")

	got, err := LoadPostgres("CHAT_DB_MAX_CONNS", 15)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.MaxConns != 15 {
		t.Errorf("MaxConns = %d, want 15", got.MaxConns)
	}

	u, perr := url.Parse(got.URL)
	if perr != nil {
		t.Fatalf("built URL not parseable: %v (url=%q)", perr, got.URL)
	}
	if u.Scheme != "postgres" {
		t.Errorf("scheme = %q, want postgres", u.Scheme)
	}
	if u.Host != "db:5433" {
		t.Errorf("host = %q, want db:5433", u.Host)
	}
	if u.Path != "/shiptrip" {
		t.Errorf("path = %q, want /shiptrip", u.Path)
	}
	user := u.User.Username()
	pass, _ := u.User.Password()
	if user != "shiptrip" || pass != "p@ss word" {
		t.Errorf("userinfo = %q:%q, want shiptrip:p@ss word", user, pass)
	}
}

func TestLoadPostgres_DatabaseURLWins(t *testing.T) {
	clearConfigEnv(t)
	// Split vars present, but DATABASE_URL should take precedence and the
	// split vars must NOT be required (no error for missing user/pass/db).
	t.Setenv("DATABASE_URL", "postgres://u:pw@host:5432/d")

	got, err := LoadPostgres("CHAT_DB_MAX_CONNS", 10)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.URL != "postgres://u:pw@host:5432/d" {
		t.Errorf("URL = %q, want the DATABASE_URL value verbatim", got.URL)
	}
}

func TestLoadPostgres_MissingFieldsError(t *testing.T) {
	clearConfigEnv(t)
	// Nothing set: every required split var should be reported, joined.
	_, err := LoadPostgres("CHAT_DB_MAX_CONNS", 10)
	if err == nil {
		t.Fatal("expected error for missing POSTGRES_* vars, got nil")
	}
	for _, want := range []string{"POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q missing mention of %s", err, want)
		}
	}
}

func TestLoadPostgres_BadDatabaseURLError(t *testing.T) {
	clearConfigEnv(t)
	// url.Parse is lenient; a control character forces a parse failure.
	t.Setenv("DATABASE_URL", "postgres://host\x7f/db")
	if _, err := LoadPostgres("CHAT_DB_MAX_CONNS", 10); err == nil {
		t.Fatal("expected parse error for malformed DATABASE_URL, got nil")
	}
}

func TestLoadPostgres_NonPositiveMaxConnsError(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("DATABASE_URL", "postgres://u:pw@host:5432/d")
	t.Setenv("CHAT_DB_MAX_CONNS", "0")
	if _, err := LoadPostgres("CHAT_DB_MAX_CONNS", 10); err == nil {
		t.Fatal("expected error for max conns 0, got nil")
	}
}

func TestLoadPostgres_NonIntMaxConnsError(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("DATABASE_URL", "postgres://u:pw@host:5432/d")
	t.Setenv("CHAT_DB_MAX_CONNS", "lots")
	if _, err := LoadPostgres("CHAT_DB_MAX_CONNS", 10); err == nil {
		t.Fatal("expected error for non-int max conns, got nil")
	}
}

// ── Redis / JWT ────────────────────────────────────────────────────────────

func TestLoadRedis(t *testing.T) {
	clearConfigEnv(t)
	if _, err := LoadRedis(); err == nil {
		t.Error("expected error when REDIS_URL unset")
	}
	t.Setenv("REDIS_URL", "redis://redis:6379/0")
	got, err := LoadRedis()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.URL != "redis://redis:6379/0" {
		t.Errorf("URL = %q", got.URL)
	}
}

func TestLoadJWT(t *testing.T) {
	clearConfigEnv(t)
	if _, err := LoadJWT(); err == nil {
		t.Error("expected error when JWT_HS256_SECRET unset")
	}
	t.Setenv("JWT_HS256_SECRET", "  s3cret  ") // trimmed
	got, err := LoadJWT()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.Secret != "s3cret" {
		t.Errorf("Secret = %q, want trimmed s3cret", got.Secret)
	}
}

// ── S3 ─────────────────────────────────────────────────────────────────────

func TestLoadS3_PathStyleDefaultsOnCustomEndpoint(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("S3_ACCESS_KEY", "ak")
	t.Setenv("S3_SECRET_KEY", "sk")
	t.Setenv("S3_ENDPOINT_URL", "http://minio:9000")

	got, err := LoadS3()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got.UsePathStyle {
		t.Error("UsePathStyle should default true when a custom endpoint is set")
	}
	if got.Region != "us-east-1" {
		t.Errorf("Region = %q, want default us-east-1", got.Region)
	}
}

func TestLoadS3_PathStyleDefaultsOffWithoutEndpoint(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("S3_ACCESS_KEY", "ak")
	t.Setenv("S3_SECRET_KEY", "sk")
	// No endpoint → real AWS path; path-style should default off.
	got, err := LoadS3()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.UsePathStyle {
		t.Error("UsePathStyle should default false without a custom endpoint")
	}
}

func TestLoadS3_ExplicitPathStyleOverride(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("S3_ACCESS_KEY", "ak")
	t.Setenv("S3_SECRET_KEY", "sk")
	t.Setenv("S3_ENDPOINT_URL", "http://minio:9000")
	t.Setenv("S3_USE_PATH_STYLE", "false")
	got, err := LoadS3()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.UsePathStyle {
		t.Error("explicit S3_USE_PATH_STYLE=false should override the endpoint default")
	}
}

func TestLoadS3_MissingKeysError(t *testing.T) {
	clearConfigEnv(t)
	if _, err := LoadS3(); err == nil {
		t.Error("expected error when S3 access/secret keys unset")
	}
}

// ── KYC gRPC ───────────────────────────────────────────────────────────────

func TestLoadKYCGRPC(t *testing.T) {
	tests := []struct {
		name    string
		target  string
		mode    string
		token   string
		wantErr bool
	}{
		{name: "missing target", target: "", mode: "bearer", token: "t", wantErr: true},
		{name: "default mode is mtls", target: "django:50051", mode: "", token: "", wantErr: false},
		{name: "bearer without token", target: "django:50051", mode: "bearer", token: "", wantErr: true},
		{name: "bearer with token", target: "django:50051", mode: "bearer", token: "t", wantErr: false},
		{name: "mode case-insensitive", target: "django:50051", mode: "MTLS", token: "", wantErr: false},
		{name: "unknown mode", target: "django:50051", mode: "kerberos", token: "", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			clearConfigEnv(t)
			t.Setenv("KYC_GRPC_TARGET", tt.target)
			t.Setenv("GRPC_AUTH_MODE", tt.mode)
			t.Setenv("GRPC_BEARER_TOKEN", tt.token)

			got, err := LoadKYCGRPC()
			if tt.wantErr {
				if err == nil {
					t.Fatalf("expected error, got nil (%+v)", got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if tt.mode == "" && got.AuthMode != "mtls" {
				t.Errorf("AuthMode = %q, want default mtls", got.AuthMode)
			}
		})
	}
}

// ── FCM ────────────────────────────────────────────────────────────────────

func TestLoadFCM_DisabledByDefault(t *testing.T) {
	clearConfigEnv(t)
	got, err := LoadFCM()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.Enabled {
		t.Error("FCM should default disabled")
	}
	// Defaults still populated even when off.
	if got.Stream != "notif:fcm" {
		t.Errorf("Stream = %q, want default notif:fcm", got.Stream)
	}
	if got.ConsumerGroup != "notif-fcm-workers" {
		t.Errorf("ConsumerGroup = %q", got.ConsumerGroup)
	}
}

func TestLoadFCM_EnabledRequiresProjectAndCreds(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("FCM_ENABLED", "true")
	_, err := LoadFCM()
	if err == nil {
		t.Fatal("expected error: enabled FCM with no project/creds")
	}
	for _, want := range []string{"FCM_PROJECT_ID", "FCM_CREDENTIALS_PATH"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q missing mention of %s", err, want)
		}
	}
}

func TestLoadFCM_EnabledHappyPath(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("FCM_ENABLED", "true")
	t.Setenv("FCM_PROJECT_ID", "shiptrip-prod")
	t.Setenv("FCM_CREDENTIALS_PATH", "/run/secrets/fcm.json")
	got, err := LoadFCM()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got.Enabled || got.ProjectID != "shiptrip-prod" || got.CredentialsPath != "/run/secrets/fcm.json" {
		t.Errorf("unexpected config: %+v", got)
	}
}

func TestLoadFCM_ConsumerNameFallsBackToHostname(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("HOSTNAME", "notif-pod-7")
	got, err := LoadFCM()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.ConsumerName != "notif-pod-7" {
		t.Errorf("ConsumerName = %q, want HOSTNAME fallback notif-pod-7", got.ConsumerName)
	}
}

func TestLoadFCM_BadEnabledBoolError(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("FCM_ENABLED", "maybe")
	if _, err := LoadFCM(); err == nil {
		t.Error("expected error for non-bool FCM_ENABLED")
	}
}

// ── misc helpers ───────────────────────────────────────────────────────────

func TestHTTPAddrAndString(t *testing.T) {
	clearConfigEnv(t)
	if got := HTTPAddr("NOTIF_HTTP_ADDR", ":8082"); got != ":8082" {
		t.Errorf("HTTPAddr fallback = %q, want :8082", got)
	}
	t.Setenv("NOTIF_HTTP_ADDR", ":9999")
	if got := HTTPAddr("NOTIF_HTTP_ADDR", ":8082"); got != ":9999" {
		t.Errorf("HTTPAddr = %q, want :9999", got)
	}
	if got := String("BUCKET", "fallback"); got != "fallback" {
		t.Errorf("String fallback = %q", got)
	}
}

func TestLoadLogger(t *testing.T) {
	clearConfigEnv(t)
	// Empty service name is a programming error → coerced to "unknown".
	if got := LoadLogger(""); got.Service != "unknown" {
		t.Errorf("Service = %q, want unknown", got.Service)
	}
	if got := LoadLogger("notification"); got.Service != "notification" || got.Level != "info" {
		t.Errorf("LoadLogger = %+v, want {notification info}", got)
	}
	t.Setenv("LOG_LEVEL", "debug")
	if got := LoadLogger("kyc"); got.Level != "debug" {
		t.Errorf("Level = %q, want debug", got.Level)
	}
}
