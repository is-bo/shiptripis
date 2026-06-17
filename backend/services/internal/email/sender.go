// Package email is the Go-side transactional-email service. Django renders
// the subject + body (signup verification, password-reset OTP, …) and XADDs
// an entry onto the durable `email:send` Redis Stream; this service consumes
// it and sends the mail over SMTP.
//
// Why a durable stream (not pub/sub): Django's redis_bus.publish_after_commit
// is fire-and-forget PUB/SUB — a message published while this consumer is down
// is lost. For an OTP that the user is actively waiting on, a lost email is a
// dead end. The stream (capped MAXLEN ~ 10000, per CLAUDE.md §G1) buffers
// across a brief consumer outage and replays on reconnect.
//
// Scope boundary: this service is a pure SMTP transport. It NEVER owns email
// copy, templates, or i18n — those stay in Django next to the product logic.
// The payload arrives fully rendered.
package email

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
)

// EmailSender is the swap point for the real SMTP backend. Mirrors the
// notification service's FCMSender seam: cmd/email injects a concrete
// smtpSender in production; tests inject a fake; LogOnlySender is the
// pre-config / dev stub.
type EmailSender interface {
	Send(ctx context.Context, p EmailPayload) error
}

// EmailPayload is the wire shape Django writes onto the stream, rendered.
// Kept here as the contract since the Go side reads it (mirrors fcm.go's
// FCMPayload). Subject and Body are produced by Django; Go does not template.
type EmailPayload struct {
	EventID string `json:"event_id"`
	To      string `json:"to"`
	Subject string `json:"subject"`
	Body    string `json:"body"`
	// Kind is "verify" | "reset" — used only for log/metric labels. Go does
	// not branch sending behaviour on it (all kinds are the same SMTP send).
	Kind string `json:"kind,omitempty"`
}

// decodePayload pulls the JSON `payload` field from the stream entry. Django
// writes a single `payload` field (matches the redis_bus envelope shape);
// `event_id` is also denormalised as its own field for cheap filtering, but
// the authoritative copy is inside the JSON.
func decodePayload(values map[string]any) (EmailPayload, error) {
	raw := stringField(values, "payload")
	if raw == "" {
		return EmailPayload{}, errors.New("missing payload field")
	}
	var p EmailPayload
	if err := json.Unmarshal([]byte(raw), &p); err != nil {
		return EmailPayload{}, fmt.Errorf("unmarshal: %w", err)
	}
	if p.To == "" {
		return EmailPayload{}, errors.New("missing recipient (to)")
	}
	if p.Subject == "" {
		return EmailPayload{}, errors.New("missing subject")
	}
	// event_id may be carried on the stream entry's own field; backfill from
	// there if the JSON omitted it, so the dedup key is always populated.
	if p.EventID == "" {
		p.EventID = stringField(values, "event_id")
	}
	return p, nil
}

func stringField(values map[string]any, key string) string {
	v, ok := values[key]
	if !ok {
		return ""
	}
	s, ok := v.(string)
	if !ok {
		return ""
	}
	return s
}

// LogOnlySender is the dev / pre-config stub. Logs the would-be send and
// returns nil so the consumer flow can be exercised end-to-end without a real
// SMTP server (mirrors notification.LogOnlySender). cmd/email installs it when
// EMAIL_ENABLED is false; swap for the real smtpSender by passing a different
// Sender to NewConsumer.
type LogOnlySender struct {
	Log *slog.Logger
}

func (s LogOnlySender) Send(_ context.Context, p EmailPayload) error {
	log := s.Log
	if log == nil {
		log = slog.Default()
	}
	log.Info("email: would-send (stub)",
		"event_id", p.EventID,
		"to", p.To,
		"subject", p.Subject,
		"kind", p.Kind,
	)
	return nil
}
