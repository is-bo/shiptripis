package auth

import (
	"bytes"
	"errors"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const testSecret = "test-secret-do-not-use-in-prod"

// signToken builds an HS256 token with the given claims and an optional
// override of the signing method (used for the alg-attack tests).
func signToken(t *testing.T, c Claims, method jwt.SigningMethod, secret []byte) string {
	t.Helper()
	if method == nil {
		method = jwt.SigningMethodHS256
	}
	tok := jwt.NewWithClaims(method, c)
	s, err := tok.SignedString(secret)
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	return s
}

func validClaims(now time.Time) Claims {
	return Claims{
		UserID: 42,
		Role:   "sender",
		Type:   "access",
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(5 * time.Minute)),
			ID:        "jti-1",
		},
	}
}

func newValidator(t *testing.T) *Validator {
	t.Helper()
	v, err := NewValidator(testSecret, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatalf("NewValidator: %v", err)
	}
	return v
}

func TestNewValidator_RejectsEmptySecret(t *testing.T) {
	if _, err := NewValidator("", nil); err == nil {
		t.Fatal("want error on empty secret, got nil")
	}
}

func TestNewValidator_NilLoggerDefaults(t *testing.T) {
	// Must not panic — nil logger should fall back to slog.Default().
	v, err := NewValidator(testSecret, nil)
	if err != nil {
		t.Fatalf("NewValidator: %v", err)
	}
	if v.logger == nil {
		t.Fatal("logger must default when nil is passed")
	}
}

func TestValidate_AcceptsValidAccessToken(t *testing.T) {
	v := newValidator(t)
	tok := signToken(t, validClaims(time.Now()), nil, []byte(testSecret))

	got, err := v.Validate(tok)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if got.UserID != 42 || got.Role != "sender" || got.Type != "access" {
		t.Fatalf("claims roundtrip mismatch: %+v", got)
	}
}

func TestValidate_RejectsWrongSecret(t *testing.T) {
	v := newValidator(t)
	tok := signToken(t, validClaims(time.Now()), nil, []byte("different-secret"))

	if _, err := v.Validate(tok); err == nil {
		t.Fatal("want error on wrong-secret token, got nil")
	}
}

// G5 / alg=none attack guard. The validator declares HS256-only via
// jwt.WithValidMethods; signing with HS512 must fail.
func TestValidate_RejectsNonHS256Algorithm(t *testing.T) {
	v := newValidator(t)
	tok := signToken(t, validClaims(time.Now()), jwt.SigningMethodHS512, []byte(testSecret))

	if _, err := v.Validate(tok); err == nil {
		t.Fatal("want error on HS512-signed token, got nil")
	}
}

// alg=none is the classic JWT attack — an attacker mints tokens with no
// signature. jwt/v5 refuses to sign these, so we craft the token by hand.
func TestValidate_RejectsAlgNoneToken(t *testing.T) {
	v := newValidator(t)
	// Header: {"alg":"none","typ":"JWT"}  base64url
	header := "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"
	// Payload: a valid-looking access claim. Body is irrelevant; the
	// validator must reject before consulting it.
	payload := "eyJ1c2VyX2lkIjo0Miwicm9sZSI6InNlbmRlciIsInR5cCI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0"
	tok := header + "." + payload + "."

	if _, err := v.Validate(tok); err == nil {
		t.Fatal("want error on alg=none token, got nil")
	}
}

func TestValidate_RejectsExpiredBeyondLeeway(t *testing.T) {
	v := newValidator(t)
	now := time.Now()
	c := validClaims(now)
	c.ExpiresAt = jwt.NewNumericDate(now.Add(-time.Minute)) // 60s ago, well past 30s leeway
	tok := signToken(t, c, nil, []byte(testSecret))

	if _, err := v.Validate(tok); err == nil {
		t.Fatal("want error on expired token, got nil")
	}
}

// G2 — the 30s clock-skew leeway. A token expired 10s ago must still
// validate; one expired 60s ago must not (covered above).
func TestValidate_AcceptsExpiredWithinLeeway(t *testing.T) {
	v := newValidator(t)
	now := time.Now()
	c := validClaims(now)
	c.ExpiresAt = jwt.NewNumericDate(now.Add(-10 * time.Second))
	tok := signToken(t, c, nil, []byte(testSecret))

	if _, err := v.Validate(tok); err != nil {
		t.Fatalf("token expired 10s ago must pass under 30s leeway: %v", err)
	}
}

func TestValidate_RejectsRefreshToken(t *testing.T) {
	v := newValidator(t)
	c := validClaims(time.Now())
	c.Type = "refresh"
	tok := signToken(t, c, nil, []byte(testSecret))

	_, err := v.Validate(tok)
	if err == nil {
		t.Fatal("refresh token must not authenticate; got nil error")
	}
	if !strings.Contains(err.Error(), "refresh") {
		t.Fatalf("error should mention token type, got: %v", err)
	}
}

func TestValidate_RejectsMissingType(t *testing.T) {
	v := newValidator(t)
	c := validClaims(time.Now())
	c.Type = ""
	tok := signToken(t, c, nil, []byte(testSecret))

	if _, err := v.Validate(tok); err == nil {
		t.Fatal("token with empty typ must be rejected")
	}
}

func TestValidate_RejectsZeroUserID(t *testing.T) {
	v := newValidator(t)
	c := validClaims(time.Now())
	c.UserID = 0
	tok := signToken(t, c, nil, []byte(testSecret))

	if _, err := v.Validate(tok); err == nil {
		t.Fatal("token with user_id=0 must be rejected")
	}
}

func TestValidate_RejectsMalformedToken(t *testing.T) {
	v := newValidator(t)
	cases := []string{
		"",
		"not.a.token",
		"only-one-part",
		"two.parts",
	}
	for _, tok := range cases {
		if _, err := v.Validate(tok); err == nil {
			t.Errorf("malformed token %q must be rejected", tok)
		}
	}
}

// Drift warning: when iat sits beyond driftWarnThreshold (5s) into the
// future but inside leeway (30s), the token is accepted AND a warning
// is logged. Both halves matter — silent acceptance is exactly what G2
// warns against.
func TestValidate_LogsDriftWarningWhenIatAheadOfNow(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn}))
	v, err := NewValidator(testSecret, logger)
	if err != nil {
		t.Fatalf("NewValidator: %v", err)
	}

	now := time.Now()
	c := validClaims(now)
	c.IssuedAt = jwt.NewNumericDate(now.Add(15 * time.Second)) // > 5s warn, < 30s leeway
	tok := signToken(t, c, nil, []byte(testSecret))

	if _, err := v.Validate(tok); err != nil {
		t.Fatalf("iat 15s ahead must validate under 30s leeway: %v", err)
	}
	if !strings.Contains(buf.String(), "clock drift") {
		t.Fatalf("expected drift warning in log, got: %s", buf.String())
	}
}

func TestValidate_NoDriftWarningForFreshToken(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn}))
	v, err := NewValidator(testSecret, logger)
	if err != nil {
		t.Fatalf("NewValidator: %v", err)
	}

	tok := signToken(t, validClaims(time.Now()), nil, []byte(testSecret))
	if _, err := v.Validate(tok); err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if buf.Len() != 0 {
		t.Fatalf("expected no drift log for fresh token, got: %s", buf.String())
	}
}

func TestValidate_ErrorWrapsJWTError(t *testing.T) {
	v := newValidator(t)
	now := time.Now()
	c := validClaims(now)
	c.ExpiresAt = jwt.NewNumericDate(now.Add(-time.Hour))
	tok := signToken(t, c, nil, []byte(testSecret))

	_, err := v.Validate(tok)
	if err == nil {
		t.Fatal("want error")
	}
	// jwt/v5 exposes typed sentinels; the validator wraps with %w so
	// errors.Is keeps working — important for callers that want to
	// distinguish "expired" (refresh-and-retry) from "tampered" (401).
	if !errors.Is(err, jwt.ErrTokenExpired) {
		t.Fatalf("error chain should contain jwt.ErrTokenExpired, got: %v", err)
	}
}

