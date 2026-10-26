package config

import "testing"

func TestEmailProductionRequiresCutoffVerifiedIdentityAndMonitoredReply(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("SHIPTRIP_ENVIRONMENT", "production")
	t.Setenv("EMAIL_ENABLED", "true")
	t.Setenv("EMAIL_PROVIDER", "sender_net")
	t.Setenv("EMAIL_SMTP_HOST", "smtp.sender.net")
	t.Setenv("EMAIL_SMTP_PORT", "587")
	t.Setenv("EMAIL_SMTP_USERNAME", "test-placeholder")
	t.Setenv("EMAIL_SMTP_PASSWORD", "test-placeholder")
	t.Setenv("EMAIL_FROM_ADDR", "notifications@example.invalid")
	if _, err := LoadEmail(); err == nil {
		t.Fatal("missing activation gates accepted")
	}
	t.Setenv("EMAIL_REPLY_TO", "support@example.invalid")
	t.Setenv("EMAIL_ACTIVATION_NOT_BEFORE", "2026-10-18T00:00:00Z")
	t.Setenv("EMAIL_SENDING_DOMAIN_VERIFIED", "true")
	got, err := LoadEmail()
	if err != nil {
		t.Fatal(err)
	}
	if got.FromName != "Wassla" || got.ReplyTo != "support@example.invalid" || got.SMTPTimeout.Seconds() != 10 {
		t.Fatal("sender contract mismatch")
	}
	for _, key := range []string{"EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_ACTIVATION_NOT_BEFORE", "EMAIL_USE_TLS", "EMAIL_REPLY_TO", "EMAIL_SMTP_TIMEOUT_SECONDS", "EMAIL_RATE_LIMIT_PER_MINUTE"} {
		t.Run(key, func(t *testing.T) {
			t.Setenv(key, "invalid")
			if _, err := LoadEmail(); err == nil {
				t.Fatal("malformed configuration accepted")
			}
		})
	}
}
