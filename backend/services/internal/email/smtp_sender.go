package email

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"regexp"
	"strings"
	"time"

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
	ReplyTo  string
	Timeout  time.Duration

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
	client  *mail.Client
	host    string // named in failure logs; never the recipient
	from    string // formatted "Name <addr>" or bare addr — set on each Msg
	name    string
	replyTo string
	log     *slog.Logger
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

	if cfg.Timeout == 0 {
		cfg.Timeout = 10 * time.Second
	}
	opts := []mail.Option{mail.WithPort(cfg.Port), mail.WithTimeout(cfg.Timeout),
		mail.WithDialContextFunc(func(ctx context.Context, network, address string) (net.Conn, error) {
			raw, err := (&net.Dialer{Timeout: cfg.Timeout}).DialContext(ctx, network, address)
			if err != nil {
				return nil, err
			}
			deadline := time.Now().Add(cfg.Timeout)
			if limit, ok := ctx.Deadline(); ok && limit.Before(deadline) {
				deadline = limit
			}
			bounded := &boundedSMTPConn{Conn: raw, deadline: deadline}
			bounded.timer = time.AfterFunc(time.Until(deadline), func() { _ = raw.Close() })
			if err := bounded.SetDeadline(deadline); err != nil {
				_ = bounded.Close()
				return nil, err
			}
			if cfg.UseTLS && cfg.Port == 465 {
				secure := tls.Client(bounded, &tls.Config{ServerName: cfg.Host, MinVersion: tls.VersionTLS12})
				if err := secure.HandshakeContext(ctx); err != nil {
					_ = secure.Close()
					return nil, err
				}
				return secure, nil
			}
			return bounded, nil
		}),
	}

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
		client:  client,
		host:    cfg.Host,
		from:    cfg.FromAddr,
		name:    cfg.FromName,
		replyTo: cfg.ReplyTo,
		log:     log,
	}, nil
}

// go-mail's dial context does not cover the greeting, and later commands can
// extend deadlines. Bound the entire connection, including STARTTLS and QUIT.
type boundedSMTPConn struct {
	net.Conn
	deadline time.Time
	timer    *time.Timer
}

func (c *boundedSMTPConn) cap(t time.Time) time.Time {
	if t.IsZero() || t.After(c.deadline) {
		return c.deadline
	}
	return t
}
func (c *boundedSMTPConn) SetDeadline(t time.Time) error     { return c.Conn.SetDeadline(c.cap(t)) }
func (c *boundedSMTPConn) SetReadDeadline(t time.Time) error { return c.Conn.SetReadDeadline(c.cap(t)) }
func (c *boundedSMTPConn) SetWriteDeadline(t time.Time) error {
	return c.Conn.SetWriteDeadline(c.cap(t))
}
func (c *boundedSMTPConn) Close() error { c.timer.Stop(); return c.Conn.Close() }

// Send renders p into a go-mail Msg and dials+sends it. A send failure returns
// an error so the consumer leaves the entry in the PEL and the sweeper retries.
func (s *smtpSender) Send(ctx context.Context, p EmailPayload) error {
	msg, err := s.buildMessage(p)
	if err != nil {
		// A malformed address can't be fixed by retrying — the consumer
		// already validated `to` in decodePayload, so this is rare. It is
		// permanent: the consumer acks it and Django's obligation keeps the
		// bounded retry budget. go-mail's parse error quotes the address, so
		// only the class survives into Error().
		return &PermanentError{Err: &SendFailure{Class: "invalid_message", cause: err}}
	}
	if err := s.client.DialAndSendWithContext(ctx, msg); err != nil {
		failure := newSendFailure(s.host, err)
		if msg.IsDelivered() {
			// The server accepted DATA; the error came from the RSET or QUIT
			// after it. Retrying would deliver the same mail a second time.
			s.log.Warn("email: smtp error after the message was accepted; treating as sent",
				append([]any{"event_id", p.EventID, "kind", p.Kind}, failure.LogAttrs()...)...)
			return nil
		}
		if code := permanentReplyCode(err); code != 0 {
			return &PermanentError{Err: failure, Code: code}
		}
		return failure
	}
	// Recipient addresses are PII. Event id + template kind are sufficient for
	// correlation with the PostgreSQL outbox and provider diagnostics.
	s.log.Debug("email sent", "event_id", p.EventID, "kind", p.Kind)
	return nil
}

// SendFailure is the log-safe form of an SMTP send error. go-mail's own error
// text names the affected recipients ("affected recipient(s): <address>"), and
// a 4xx/5xx reply line or an AUTH rejection often quotes an address too, so
// Error() carries only fixed vocabulary: the failure class, the relay host,
// and the numeric reply codes. The raw error stays reachable through Unwrap
// for classification, and must never be logged.
type SendFailure struct {
	// Class is one of: smtp_reply, dial, tls, auth, timeout, canceled,
	// transport, invalid_message.
	Class string
	// Host is the configured SMTP relay. Empty when the send never dialled.
	Host string
	// Code and Enhanced are the SMTP reply code and RFC 3463 status (for
	// example 451 and "4.2.2") when Class is smtp_reply.
	Code     int
	Enhanced string
	// Stage is go-mail's fixed description of the step that failed (for
	// example "SMTP RCPT TO failed").
	Stage string
	cause error
}

func (e *SendFailure) Error() string {
	var b strings.Builder
	b.WriteString("email: smtp send failed: ")
	b.WriteString(e.Class)
	if e.Stage != "" {
		b.WriteString(" at ")
		b.WriteString(e.Stage)
	}
	if e.Code != 0 {
		fmt.Fprintf(&b, " (reply %d", e.Code)
		if e.Enhanced != "" {
			b.WriteString(" ")
			b.WriteString(e.Enhanced)
		}
		b.WriteString(")")
	}
	if e.Host != "" {
		b.WriteString(" host ")
		b.WriteString(e.Host)
	}
	return b.String()
}

func (e *SendFailure) Unwrap() error { return e.cause }

// LogAttrs returns the slog attributes for this failure. Nothing here can
// carry a recipient address.
func (e *SendFailure) LogAttrs() []any {
	attrs := []any{"failure", e.Class}
	if e.Stage != "" {
		attrs = append(attrs, "stage", e.Stage)
	}
	if e.Code != 0 {
		attrs = append(attrs, "smtp_code", e.Code)
	}
	if e.Enhanced != "" {
		attrs = append(attrs, "smtp_status", e.Enhanced)
	}
	if e.Host != "" {
		attrs = append(attrs, "smtp_host", e.Host)
	}
	return attrs
}

// enhancedStatusPattern is RFC 3463's class.subject.detail. Anything else in
// that field is dropped rather than logged.
var enhancedStatusPattern = regexp.MustCompile(`^[245]\.\d{1,3}\.\d{1,3}$`)

// newSendFailure classifies a go-mail error without keeping any of its text.
func newSendFailure(host string, err error) *SendFailure {
	f := &SendFailure{Host: host, cause: err}
	var sendErr *mail.SendError
	switch {
	case errors.As(err, &sendErr):
		f.Class = "smtp_reply"
		f.Stage = sendErr.Reason.String()
		f.Code = sendErr.ErrorCode()
		if status := sendErr.EnhancedStatusCode(); enhancedStatusPattern.MatchString(status) {
			f.Enhanced = status
		}
	case errors.Is(err, context.DeadlineExceeded):
		f.Class = "timeout"
	case errors.Is(err, context.Canceled):
		f.Class = "canceled"
	default:
		// go-mail wraps dial, STARTTLS and AUTH failures as plain text. Only
		// the matched class is kept; the text itself can quote the server.
		text := err.Error()
		switch {
		case strings.Contains(text, "SMTP AUTH failed"):
			f.Class = "auth"
		case strings.Contains(strings.ToLower(text), "tls"):
			f.Class = "tls"
		case strings.HasPrefix(text, "dial failed"):
			f.Class = "dial"
		default:
			f.Class = "transport"
		}
	}
	return f
}

// SendFailureLogAttrs returns log attributes for any EmailSender error: the
// SendFailure or SenderNetFailure fields when there is one, and otherwise only
// the error's Go type. Send errors are never logged as text, because an SMTP
// error's text and an API answer can both name the recipient.
func SendFailureLogAttrs(err error) []any {
	var failure *SendFailure
	if errors.As(err, &failure) {
		return failure.LogAttrs()
	}
	var apiFailure *SenderNetFailure
	if errors.As(err, &apiFailure) {
		return apiFailure.LogAttrs()
	}
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return []any{"failure", "timeout"}
	case errors.Is(err, context.Canceled):
		return []any{"failure", "canceled"}
	}
	return []any{"failure", "unclassified", "err_type", fmt.Sprintf("%T", err)}
}

// permanentReplyCode returns the 5xx reply code when the SMTP server itself
// rejected a send command (unknown mailbox, rejected content, message too
// large), and 0 otherwise. Only a server reply counts: dial, TLS, auth and
// connection failures carry no reply code and stay retryable, as do 4xx.
func permanentReplyCode(err error) int {
	var sendErr *mail.SendError
	if !errors.As(err, &sendErr) {
		return 0
	}
	if code := sendErr.ErrorCode(); code >= 500 && code < 600 {
		return code
	}
	return 0
}

// buildMessage is the pure (no-network) half of Send — unit-testable without
// an SMTP server. It sets From (with optional display name), To, Subject and
// the body.
//
// The plain-text part is always the primary body: a client that cannot render
// HTML, a screen reader, and a spam filter all read that one, and Django built
// both parts from the same document so they cannot disagree. The HTML part is
// attached as an alternative only when Django supplied one; there is still no
// templating on this side.
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
	if s.replyTo != "" {
		if err := msg.ReplyTo(s.replyTo); err != nil {
			return nil, errors.New("invalid reply-to")
		}
	}
	msg.Subject(p.Subject)
	if p.EventID != "" {
		identity := sha256.Sum256([]byte(p.EventID))
		domain := s.from[strings.LastIndex(s.from, "@")+1:]
		msg.SetMessageIDWithValue(fmt.Sprintf("wacla-%x@%s", identity, domain))
	}
	msg.SetBodyString(mail.TypeTextPlain, p.Body)
	if p.HTML != "" {
		msg.AddAlternativeString(mail.TypeTextHTML, p.HTML)
	}
	return msg, nil
}
