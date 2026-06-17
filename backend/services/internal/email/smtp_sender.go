package email

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/wneessen/go-mail"
)

// SMTPConfig is the subset of config.Email the sender needs. Kept as a local
// struct so internal/email doesn't import pkg/config (cmd/email translates).
type SMTPConfig struct {
	Host     string
	Port     int
	Username string
	Password string
	FromAddr string
	FromName string

	// UseTLS selects the transport security policy:
	//   - true  + port 465 → implicit TLS (SSL on connect)
	//   - true  + other    → mandatory STARTTLS (587, the common case)
	//   - false            → no TLS (port 25 / dev MailHog on 1025)
	UseTLS bool
}

// smtpSender is the production EmailSender backed by github.com/wneessen/go-mail.
// One *mail.Client is built per process at boot and reused; go-mail dials per
// DialAndSend call, so the client is safe to share across the consumer's
// concurrent handlers.
type smtpSender struct {
	client *mail.Client
	from   string // formatted "Name <addr>" or bare addr — set on each Msg
	name   string
	log    *slog.Logger
}

// NewSMTPSender builds a real EmailSender. Fails loud on bad config (CLAUDE.md
// §9: a half-configured mail deploy should fail at boot, not on the first OTP).
// Host, Port, and FromAddr are required (LoadEmail already enforces this when
// EMAIL_ENABLED=true; the guards here keep the constructor total).
func NewSMTPSender(cfg SMTPConfig, log *slog.Logger) (EmailSender, error) {
	if log == nil {
		log = slog.Default()
	}
	if cfg.Host == "" {
		return nil, errors.New("email: smtp host is required")
	}
	if cfg.Port == 0 {
		return nil, errors.New("email: smtp port is required")
	}
	if cfg.FromAddr == "" {
		return nil, errors.New("email: from address is required")
	}

	opts := []mail.Option{mail.WithPort(cfg.Port)}

	switch {
	case cfg.UseTLS && cfg.Port == 465:
		// Implicit TLS on connect (SMTPS).
		opts = append(opts, mail.WithSSL())
	case cfg.UseTLS:
		// STARTTLS, required — refuse to send in the clear if the server
		// doesn't offer it. This is the right default for real relays
		// (Brevo/Gmail/Mailgun on 587).
		opts = append(opts, mail.WithTLSPolicy(mail.TLSMandatory))
	default:
		// Dev / MailHog: no transport security.
		opts = append(opts, mail.WithTLSPolicy(mail.NoTLS))
	}

	// Only configure auth when a username is provided. Dev SMTP sinks
	// (MailHog) accept unauthenticated mail; forcing AUTH there would fail.
	if cfg.Username != "" {
		opts = append(opts,
			mail.WithSMTPAuth(mail.SMTPAuthPlain),
			mail.WithUsername(cfg.Username),
			mail.WithPassword(cfg.Password),
		)
	}

	client, err := mail.NewClient(cfg.Host, opts...)
	if err != nil {
		return nil, fmt.Errorf("email: build smtp client: %w", err)
	}

	log.Info("email smtp sender ready",
		"host", cfg.Host,
		"port", cfg.Port,
		"tls", cfg.UseTLS,
		"auth", cfg.Username != "",
		"from", cfg.FromAddr,
	)
	return &smtpSender{
		client: client,
		from:   cfg.FromAddr,
		name:   cfg.FromName,
		log:    log,
	}, nil
}

// Send renders p into a go-mail Msg and dials+sends it. A send failure returns
// an error so the consumer leaves the entry in the PEL and the sweeper retries.
func (s *smtpSender) Send(ctx context.Context, p EmailPayload) error {
	msg, err := s.buildMessage(p)
	if err != nil {
		// A malformed address can't be fixed by retrying — but the consumer
		// already validated `to` in decodePayload, so this is rare. Surface
		// it; handle() logs and the sweeper will keep retrying (the daily
		// G6b audit catches a permanently-stuck entry).
		return fmt.Errorf("email: build message (event %s): %w", p.EventID, err)
	}
	if err := s.client.DialAndSendWithContext(ctx, msg); err != nil {
		return fmt.Errorf("email: smtp send (event %s): %w", p.EventID, err)
	}
	s.log.Debug("email sent", "event_id", p.EventID, "to", p.To, "kind", p.Kind)
	return nil
}

// buildMessage is the pure (no-network) half of Send — unit-testable without
// an SMTP server. It sets From (with optional display name), To, Subject, and
// a plaintext body. V1 is plaintext only (no HTML/attachments — §out of scope).
func (s *smtpSender) buildMessage(p EmailPayload) (*mail.Msg, error) {
	msg := mail.NewMsg()
	if s.name != "" {
		if err := msg.FromFormat(s.name, s.from); err != nil {
			return nil, fmt.Errorf("from: %w", err)
		}
	} else {
		if err := msg.From(s.from); err != nil {
			return nil, fmt.Errorf("from: %w", err)
		}
	}
	if err := msg.To(p.To); err != nil {
		return nil, fmt.Errorf("to: %w", err)
	}
	msg.Subject(p.Subject)
	msg.SetBodyString(mail.TypeTextPlain, p.Body)
	return msg, nil
}
