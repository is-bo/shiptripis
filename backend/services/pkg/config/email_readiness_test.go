package config

import (
	"strings"
	"testing"
)

func productionSenderNet(t *testing.T) {
	t.Helper()
	clearConfigEnv(t)
	t.Setenv("SHIPTRIP_ENVIRONMENT", "production")
	t.Setenv("EMAIL_ENABLED", "true")
	t.Setenv("EMAIL_PROVIDER", "sender_net")
	t.Setenv("SENDER_NET_API_TOKEN", testSenderNetToken)
}

func TestEmailProductionRequiresCutoffAndVerifiedDomain(t *testing.T) {
	productionSenderNet(t)
	if _, err := LoadEmail(); err == nil {
		t.Fatal("missing activation gates accepted")
	}
	t.Setenv("EMAIL_ACTIVATION_NOT_BEFORE", "2026-10-18T00:00:00Z")
	if _, err := LoadEmail(); err == nil {
		t.Fatal("unverified sending domain accepted")
	}
	t.Setenv("EMAIL_SENDING_DOMAIN_VERIFIED", "true")
	got, err := LoadEmail()
	if err != nil {
		t.Fatal(err)
	}
	if got.FromName != "Wassla" || got.FromAddr != "contact@wassla.eu" || got.ReplyTo != "contact@wassla.eu" || got.Timeout.Seconds() != 10 {
		t.Fatal("sender contract mismatch")
	}
	// Sender.net is HTTPS only: EMAIL_USE_TLS is an SMTP setting.
	t.Setenv("EMAIL_USE_TLS", "false")
	if _, err := LoadEmail(); err != nil {
		t.Fatalf("Sender.net refused over an SMTP-only setting: %v", err)
	}
	for _, key := range []string{"EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_ACTIVATION_NOT_BEFORE", "EMAIL_USE_TLS", "EMAIL_REPLY_TO", "EMAIL_FROM_ADDR", "EMAIL_TIMEOUT_SECONDS", "EMAIL_RATE_LIMIT_PER_MINUTE", "SENDER_NET_API_TOKEN"} {
		t.Run(key, func(t *testing.T) {
			t.Setenv(key, "invalid")
			_, err := LoadEmail()
			if err == nil {
				t.Fatal("malformed configuration accepted")
			}
			if strings.Contains(err.Error(), testSenderNetToken) {
				t.Fatal("the error names the token")
			}
		})
	}
}

func TestEmailProductionSMTPStillRequiresTLS(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("SHIPTRIP_ENVIRONMENT", "production")
	t.Setenv("EMAIL_ENABLED", "true")
	t.Setenv("EMAIL_PROVIDER", "smtp")
	t.Setenv("EMAIL_SMTP_HOST", "smtp.example.invalid")
	t.Setenv("EMAIL_SMTP_PORT", "587")
	t.Setenv("EMAIL_ACTIVATION_NOT_BEFORE", "2026-10-18T00:00:00Z")
	t.Setenv("EMAIL_SENDING_DOMAIN_VERIFIED", "true")
	if _, err := LoadEmail(); err != nil {
		t.Fatal(err)
	}
	t.Setenv("EMAIL_USE_TLS", "false")
	if _, err := LoadEmail(); err == nil {
		t.Fatal("production SMTP without TLS accepted")
	}
}
