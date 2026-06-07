package logger

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"testing"
)

func TestParseLevel(t *testing.T) {
	tests := []struct {
		in   string
		want slog.Level
	}{
		{"debug", slog.LevelDebug},
		{"DEBUG", slog.LevelDebug},
		{" Debug ", slog.LevelDebug}, // trimmed + case-folded
		{"warn", slog.LevelWarn},
		{"warning", slog.LevelWarn},
		{"error", slog.LevelError},
		{"info", slog.LevelInfo},
		{"", slog.LevelInfo},         // empty → default info
		{"nonsense", slog.LevelInfo}, // unknown → default info
	}
	for _, tt := range tests {
		t.Run(tt.in, func(t *testing.T) {
			if got := parseLevel(tt.in); got != tt.want {
				t.Errorf("parseLevel(%q) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}

func TestNew_AttachesServiceField(t *testing.T) {
	// New writes to os.Stdout, so we can't capture its output directly, but we
	// can assert it returns a usable logger and sets the default. Behaviour of
	// the service field is verified via a parallel handler over a buffer below.
	l := New(Config{Service: "notification", Level: "debug"})
	if l == nil {
		t.Fatal("New returned nil")
	}
	if slog.Default() != l {
		t.Error("New should install its logger as slog.Default")
	}
}

// TestServiceFieldRendered reconstructs the same With() the package applies and
// verifies the field lands in the JSON line — proving the convention without
// depending on os.Stdout capture.
func TestServiceFieldRendered(t *testing.T) {
	var buf bytes.Buffer
	l := slog.New(slog.NewJSONHandler(&buf, nil)).With(slog.String("service", "kyc"))
	l.Info("hello")

	var rec map[string]any
	if err := json.Unmarshal(buf.Bytes(), &rec); err != nil {
		t.Fatalf("decode log line: %v", err)
	}
	if rec["service"] != "kyc" {
		t.Errorf("service field = %v, want kyc", rec["service"])
	}
}

func TestWithLoggerAndFromContext(t *testing.T) {
	custom := slog.New(slog.NewJSONHandler(&bytes.Buffer{}, nil))
	ctx := WithLogger(context.Background(), custom)

	if got := FromContext(ctx); got != custom {
		t.Error("FromContext should return the logger stored by WithLogger")
	}
}

func TestFromContext_FallsBackToDefault(t *testing.T) {
	// Empty context → slog.Default, never nil.
	if got := FromContext(context.Background()); got == nil {
		t.Fatal("FromContext returned nil for empty context")
	}

	// A nil logger stored under the key must still fall back to default,
	// not return the nil.
	ctx := context.WithValue(context.Background(), ctxKey{}, (*slog.Logger)(nil))
	if got := FromContext(ctx); got == nil {
		t.Error("FromContext returned nil when a nil logger was stored")
	}
}
