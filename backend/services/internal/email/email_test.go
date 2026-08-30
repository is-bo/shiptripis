package email

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/wneessen/go-mail"
)

// ── decodePayload ───────────────────────────────────────────────────────────

func streamValues(payload string, extra map[string]any) map[string]any {
	v := map[string]any{"payload": payload}
	for k, val := range extra {
		v[k] = val
	}
	return v
}

func mustJSON(t *testing.T, p EmailPayload) string {
	t.Helper()
	b, err := json.Marshal(p)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return string(b)
}

func TestDecodePayload(t *testing.T) {
	good := EmailPayload{
		EventID: "abc123",
		To:      "user@example.com",
		Subject: "ShipTrip verification code",
		Body:    "Your code is 123456",
		Kind:    "verify",
	}

	tests := []struct {
		name    string
		values  map[string]any
		wantErr string // substring; "" = expect success
		check   func(t *testing.T, p EmailPayload)
	}{
		{
			name:   "happy path",
			values: streamValues(mustJSON(t, good), nil),
			check: func(t *testing.T, p EmailPayload) {
				if p.To != good.To || p.Subject != good.Subject || p.Body != good.Body {
					t.Fatalf("round-trip mismatch: %+v", p)
				}
				if p.EventID != "abc123" {
					t.Fatalf("event_id = %q, want abc123", p.EventID)
				}
			},
		},
		{
			name:    "missing payload field",
			values:  map[string]any{"event_id": "x"},
			wantErr: "missing payload",
		},
		{
			name:    "non-string payload",
			values:  map[string]any{"payload": 42},
			wantErr: "missing payload", // stringField returns "" for non-string
		},
		{
			name:    "bad json",
			values:  streamValues("{not json", nil),
			wantErr: "unmarshal",
		},
		{
			name:    "missing recipient",
			values:  streamValues(mustJSON(t, EmailPayload{Subject: "s", Body: "b"}), nil),
			wantErr: "missing recipient",
		},
		{
			name:    "missing subject",
			values:  streamValues(mustJSON(t, EmailPayload{To: "a@b.c", Body: "b"}), nil),
			wantErr: "missing subject",
		},
		{
			name: "event_id backfilled from stream field",
			values: streamValues(
				mustJSON(t, EmailPayload{To: "a@b.c", Subject: "s", Body: "b"}),
				map[string]any{"event_id": "fromfield"},
			),
			check: func(t *testing.T, p EmailPayload) {
				if p.EventID != "fromfield" {
					t.Fatalf("event_id = %q, want backfilled fromfield", p.EventID)
				}
			},
		},
		{
			name:    "missing event_id",
			values:  streamValues(mustJSON(t, EmailPayload{To: "a@b.c", Subject: "s", Body: "b"}), nil),
			wantErr: "missing event_id",
		},
		{
			name: "kind optional",
			values: streamValues(
				mustJSON(t, EmailPayload{To: "a@b.c", Subject: "s", Body: "b"}),
				map[string]any{"event_id": "kind-optional"},
			),
			check: func(t *testing.T, p EmailPayload) {
				if p.Kind != "" {
					t.Fatalf("kind = %q, want empty", p.Kind)
				}
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			p, err := decodePayload(tc.values)
			if tc.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("err = %v, want containing %q", err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected err: %v", err)
			}
			if tc.check != nil {
				tc.check(t, p)
			}
		})
	}
}

// ── buildMessage (pure, no network) ─────────────────────────────────────────

func TestBuildMessage(t *testing.T) {
	p := EmailPayload{
		EventID: "e1",
		To:      "rcpt@example.com",
		Subject: "Subject line",
		Body:    "Body text",
	}

	t.Run("with display name", func(t *testing.T) {
		s := &smtpSender{from: "noreply@shiptrip.dz", name: "ShipTrip"}
		msg, err := s.buildMessage(p)
		if err != nil {
			t.Fatalf("buildMessage: %v", err)
		}
		from := msg.GetFromString()
		if len(from) != 1 || !strings.Contains(from[0], "noreply@shiptrip.dz") || !strings.Contains(from[0], "ShipTrip") {
			t.Fatalf("From = %v, want name+addr", from)
		}
		to := msg.GetToString()
		if len(to) != 1 || !strings.Contains(to[0], "rcpt@example.com") {
			t.Fatalf("To = %v", to)
		}
	})

	t.Run("without display name", func(t *testing.T) {
		s := &smtpSender{from: "noreply@shiptrip.dz"}
		msg, err := s.buildMessage(p)
		if err != nil {
			t.Fatalf("buildMessage: %v", err)
		}
		from := msg.GetFromString()
		if len(from) != 1 || !strings.Contains(from[0], "noreply@shiptrip.dz") {
			t.Fatalf("From = %v", from)
		}
	})

	t.Run("bad recipient errors", func(t *testing.T) {
		s := &smtpSender{from: "noreply@shiptrip.dz"}
		_, err := s.buildMessage(EmailPayload{To: "not-an-email", Subject: "s", Body: "b"})
		if err == nil {
			t.Fatal("expected error on malformed recipient")
		}
	})

	// A payload with no HTML must stay a single-part plain-text message: that
	// is every message this stream carried before HTML existed, and a mail
	// that claims to be multipart with an empty HTML part renders as blank in
	// most clients.
	t.Run("plain text only when no html supplied", func(t *testing.T) {
		s := &smtpSender{from: "noreply@shiptrip.dz"}
		msg, err := s.buildMessage(p)
		if err != nil {
			t.Fatalf("buildMessage: %v", err)
		}
		parts := msg.GetParts()
		if len(parts) != 1 {
			t.Fatalf("parts = %d, want 1", len(parts))
		}
		if parts[0].GetContentType() != mail.TypeTextPlain {
			t.Fatalf("content type = %v, want text/plain", parts[0].GetContentType())
		}
	})

	// With HTML the plain-text part must remain first: it is the part a client
	// without HTML, a screen reader and a spam filter all read.
	t.Run("html is attached as an alternative after the text part", func(t *testing.T) {
		s := &smtpSender{from: "noreply@shiptrip.dz"}
		withHTML := p
		withHTML.HTML = "<html><body><p>Body text</p></body></html>"
		msg, err := s.buildMessage(withHTML)
		if err != nil {
			t.Fatalf("buildMessage: %v", err)
		}
		parts := msg.GetParts()
		if len(parts) != 2 {
			t.Fatalf("parts = %d, want 2", len(parts))
		}
		if parts[0].GetContentType() != mail.TypeTextPlain {
			t.Fatalf("first part = %v, want text/plain", parts[0].GetContentType())
		}
		if parts[1].GetContentType() != mail.TypeTextHTML {
			t.Fatalf("second part = %v, want text/html", parts[1].GetContentType())
		}
	})
}

// ── NewSMTPSender validation ────────────────────────────────────────────────

func TestNewSMTPSenderValidation(t *testing.T) {
	tests := []struct {
		name    string
		cfg     SMTPConfig
		wantErr string
	}{
		{"missing host", SMTPConfig{Port: 587, FromAddr: "a@b.c"}, "host is required"},
		{"missing port", SMTPConfig{Host: "smtp.x", FromAddr: "a@b.c"}, "port is required"},
		{"missing from", SMTPConfig{Host: "smtp.x", Port: 587}, "from address is required"},
		{"valid no-auth (mailhog)", SMTPConfig{Host: "mailhog", Port: 1025, FromAddr: "a@b.c"}, ""},
		{"valid with auth", SMTPConfig{Host: "smtp.x", Port: 587, Username: "u", Password: "p", FromAddr: "a@b.c", UseTLS: true}, ""},
		{"valid implicit tls 465", SMTPConfig{Host: "smtp.x", Port: 465, FromAddr: "a@b.c", UseTLS: true}, ""},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewSMTPSender(tc.cfg, nil)
			if tc.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("err = %v, want containing %q", err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected err: %v", err)
			}
		})
	}
}

// ── LogOnlySender ───────────────────────────────────────────────────────────

func TestLogOnlySenderNeverErrors(t *testing.T) {
	s := LogOnlySender{}
	if err := s.Send(context.Background(), EmailPayload{To: "a@b.c", Subject: "s"}); err != nil {
		t.Fatalf("LogOnlySender.Send returned err: %v", err)
	}
}

// fakeSender is the test seam other packages would use to assert sends without
// a live SMTP server. Kept here to document the EmailSender interface usage.
type fakeSender struct {
	sent []EmailPayload
	err  error
}

func (f *fakeSender) Send(_ context.Context, p EmailPayload) error {
	if f.err != nil {
		return f.err
	}
	f.sent = append(f.sent, p)
	return nil
}

func TestFakeSenderSatisfiesInterface(t *testing.T) {
	var _ EmailSender = (*fakeSender)(nil)
	f := &fakeSender{}
	_ = f.Send(context.Background(), EmailPayload{To: "a@b.c"})
	if len(f.sent) != 1 {
		t.Fatalf("recorded %d sends, want 1", len(f.sent))
	}
}
