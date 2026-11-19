package email

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/mail"
	"net/url"
	"strings"
	"time"
)

// SenderNetEndpoint is Sender.net's transactional send endpoint. cmd/email
// passes it to NewSenderNetSender; tests pass an httptest server instead.
const SenderNetEndpoint = "https://api.sender.net/v2/message/send"

// senderNetMaxAnswer bounds how much of an answer is read. A success answer is
// a few dozen bytes; anything larger is drained no further.
const senderNetMaxAnswer = 64 << 10

// SenderNetConfig is the subset of config.Email the API sender needs. Kept as
// a local struct so internal/email doesn't import pkg/config (cmd/email
// translates), like SMTPConfig.
type SenderNetConfig struct {
	Endpoint string
	Token    string
	FromAddr string
	FromName string
	ReplyTo  string
	Timeout  time.Duration
}

// senderNetSender sends each payload with one Sender.net API call. It mirrors
// Django's SenderNetEmailBackend (apps/notifications/sender_net.py): the same
// JSON contract and the same failure classes.
type senderNetSender struct {
	client   *http.Client
	endpoint string
	host     string // named in failure logs; never the recipient
	token    string
	from     string
	name     string
	replyTo  string
	log      *slog.Logger
}

// NewSenderNetSender builds the API EmailSender. Fails loud on bad config, like
// NewSMTPSender: LoadEmail already enforces the token and From address when
// EMAIL_ENABLED=true; the guards here keep the constructor total.
func NewSenderNetSender(cfg SenderNetConfig, log *slog.Logger) (EmailSender, error) {
	if log == nil {
		log = slog.Default()
	}
	endpoint, err := url.Parse(cfg.Endpoint)
	if err != nil || endpoint.Host == "" || (endpoint.Scheme != "https" && endpoint.Scheme != "http") {
		return nil, errors.New("email: sender.net endpoint must be an absolute URL")
	}
	if cfg.Token == "" {
		return nil, errors.New("email: sender.net API token is required")
	}
	if cfg.FromAddr == "" {
		return nil, errors.New("email: from address is required")
	}
	replyTo, err := senderNetReplyTo(cfg.FromAddr, cfg.ReplyTo)
	if err != nil {
		return nil, err
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 10 * time.Second
	}
	transport, ok := http.DefaultTransport.(*http.Transport)
	if !ok {
		return nil, errors.New("email: default HTTP transport is unavailable")
	}
	transport = transport.Clone()
	transport.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12}
	client := &http.Client{
		Transport: transport,
		Timeout:   cfg.Timeout,
		// A redirect is not an acceptance. It is answered as a retryable
		// status instead of being followed with the bearer token.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	log.Info("email sender.net sender ready", "host", endpoint.Host, "from", cfg.FromAddr)
	return &senderNetSender{
		client:   client,
		endpoint: endpoint.String(),
		host:     endpoint.Host,
		token:    cfg.Token,
		from:     cfg.FromAddr,
		name:     cfg.FromName,
		replyTo:  replyTo,
		log:      log,
	}, nil
}

// senderNetReplyTo is the Reply-To header value to send, or "" when Reply-To
// says nothing From does not: the shipped configuration uses one address for
// both. Both are parsed and their addresses compared without case, as Django's
// SenderNetEmailBackend does, so "Wassla <CONTACT@wassla.eu>" equals
// "contact@wassla.eu". The value sent is the parsed address, with its display
// name when it has one.
func senderNetReplyTo(fromAddr, replyTo string) (string, error) {
	if replyTo == "" {
		return "", nil
	}
	from, err := mail.ParseAddress(fromAddr)
	if err != nil {
		return "", errors.New("email: from address must be an email address")
	}
	reply, err := mail.ParseAddress(replyTo)
	if err != nil {
		return "", errors.New("email: reply-to must be an email address")
	}
	if strings.EqualFold(reply.Address, from.Address) {
		return "", nil
	}
	if reply.Name == "" {
		return reply.Address, nil
	}
	return reply.String(), nil
}

type senderNetAddress struct {
	Email string `json:"email"`
	Name  string `json:"name,omitempty"`
}

type senderNetMessage struct {
	From    senderNetAddress  `json:"from"`
	To      senderNetAddress  `json:"to"`
	Subject string            `json:"subject"`
	Text    string            `json:"text,omitempty"`
	HTML    string            `json:"html,omitempty"`
	Headers map[string]string `json:"headers,omitempty"`
}

// buildMessage is the pure (no-network) half of Send. Reply-To travels as a
// custom header, and only when it differs from From (senderNetReplyTo). An
// empty subject is refused as Django refuses it: Sender would reject the
// message, so it is permanent before the network.
func (s *senderNetSender) buildMessage(p EmailPayload) (senderNetMessage, error) {
	if p.Subject == "" || strings.ContainsAny(p.Subject, "\r\n") {
		return senderNetMessage{}, errors.New("invalid subject")
	}
	to, err := mail.ParseAddress(p.To)
	if err != nil {
		return senderNetMessage{}, errors.New("invalid recipient")
	}
	m := senderNetMessage{
		From:    senderNetAddress{Email: s.from, Name: s.name},
		To:      senderNetAddress{Email: to.Address, Name: to.Name},
		Subject: p.Subject,
		Text:    p.Body,
		HTML:    p.HTML,
	}
	if s.replyTo != "" {
		m.Headers = map[string]string{"Reply-To": s.replyTo}
	}
	return m, nil
}

// Send posts one payload. A nil return means Sender answered 2xx with
// "success": true. 400 and 422 are permanent; everything else is retryable
// so a configuration error (401, 403, 404) does not burn the message.
func (s *senderNetSender) Send(ctx context.Context, p EmailPayload) error {
	m, err := s.buildMessage(p)
	if err != nil {
		return &PermanentError{Err: &SenderNetFailure{Class: "invalid_message", Host: s.host, cause: err}}
	}
	body, err := json.Marshal(m)
	if err != nil {
		return &PermanentError{Err: &SenderNetFailure{Class: "invalid_message", Host: s.host, cause: err}}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.endpoint, bytes.NewReader(body))
	if err != nil {
		return &SenderNetFailure{Class: "transport", Host: s.host, cause: err}
	}
	req.Header.Set("Authorization", "Bearer "+s.token)
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(req)
	if err != nil {
		return newSenderNetTransportFailure(s.host, err)
	}
	defer func() { _ = resp.Body.Close() }()
	answer, readErr := io.ReadAll(io.LimitReader(resp.Body, senderNetMaxAnswer))

	status := resp.StatusCode
	switch {
	case status >= 200 && status < 300:
		var result struct {
			Success bool `json:"success"`
		}
		if readErr == nil && json.Unmarshal(answer, &result) == nil && result.Success {
			s.log.Debug("email sent", "event_id", p.EventID, "kind", p.Kind)
			return nil
		}
		return &SenderNetFailure{Class: "unconfirmed", Status: status, Host: s.host}
	case status == http.StatusBadRequest || status == http.StatusUnprocessableEntity:
		return &PermanentError{Err: &SenderNetFailure{Class: "http_status", Status: status, Host: s.host}, Code: status}
	default:
		return &SenderNetFailure{Class: "http_status", Status: status, Host: s.host}
	}
}

// SenderNetFailure is the log-safe form of a Sender.net API failure. Error()
// carries only fixed vocabulary: the class, the HTTP status and the API host.
// The answer body (whose validation details can quote the recipient) is never
// kept, and the raw transport error stays reachable only through Unwrap for
// classification; it must never be logged.
type SenderNetFailure struct {
	// Class is one of: http_status, unconfirmed, timeout, canceled,
	// transport, invalid_message.
	Class string
	// Status is the HTTP status when Sender answered, otherwise 0.
	Status int
	// Host is the API host. Never the recipient.
	Host  string
	cause error
}

func (e *SenderNetFailure) Error() string {
	var b strings.Builder
	b.WriteString("email: sender.net send failed: ")
	b.WriteString(e.Class)
	if e.Status != 0 {
		fmt.Fprintf(&b, " (status %d)", e.Status)
	}
	if e.Host != "" {
		b.WriteString(" host ")
		b.WriteString(e.Host)
	}
	return b.String()
}

func (e *SenderNetFailure) Unwrap() error { return e.cause }

// LogAttrs returns the slog attributes for this failure. Nothing here can
// carry a recipient address, a subject, a body or the token.
func (e *SenderNetFailure) LogAttrs() []any {
	attrs := []any{"failure", e.Class, "provider", "sender_net"}
	if e.Status != 0 {
		attrs = append(attrs, "http_status", e.Status)
	}
	if e.Host != "" {
		attrs = append(attrs, "api_host", e.Host)
	}
	return attrs
}

// newSenderNetTransportFailure classifies an http.Client error without
// keeping any of its text.
func newSenderNetTransportFailure(host string, err error) *SenderNetFailure {
	f := &SenderNetFailure{Class: "transport", Host: host, cause: err}
	var netErr net.Error
	switch {
	case errors.Is(err, context.Canceled):
		f.Class = "canceled"
	case errors.Is(err, context.DeadlineExceeded), errors.As(err, &netErr) && netErr.Timeout():
		f.Class = "timeout"
	}
	return f
}
