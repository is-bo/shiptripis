package email

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
)

// fakeSMTP is a minimal line-level SMTP server that answers RCPT TO with a
// fixed reply, so the sender's retry classification is exercised against a
// real go-mail conversation rather than a hand-built error value.
func fakeSMTP(t *testing.T, rcptReply string) (host string, port int) {
	t.Helper()
	return fakeSMTPWith(t, rcptReply, "250 ok", nil)
}

// fakeSMTPWith also scripts the RSET reply go-mail sends after an accepted
// DATA, and counts accepted messages when accepted is non-nil.
func fakeSMTPWith(t *testing.T, rcptReply, rsetReply string, accepted *atomic.Int32) (host string, port int) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go serveFakeSMTP(conn, rcptReply, rsetReply, accepted)
		}
	}()
	addr := ln.Addr().(*net.TCPAddr)
	return addr.IP.String(), addr.Port
}

func serveFakeSMTP(conn net.Conn, rcptReply, rsetReply string, accepted *atomic.Int32) {
	defer func() { _ = conn.Close() }()
	_ = conn.SetDeadline(time.Now().Add(10 * time.Second))
	r := bufio.NewReader(conn)
	reply := func(s string) { _, _ = conn.Write([]byte(s + "\r\n")) }
	reply("220 fake.test ESMTP")
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return
		}
		verb := strings.ToUpper(strings.Fields(strings.TrimSpace(line) + " x")[0])
		switch verb {
		case "EHLO", "HELO":
			reply("250 fake.test")
		case "RCPT":
			reply(rcptReply)
		case "DATA":
			reply("354 go ahead")
			for {
				body, err := r.ReadString('\n')
				if err != nil {
					return
				}
				if strings.TrimRight(body, "\r\n") == "." {
					break
				}
			}
			if accepted != nil {
				accepted.Add(1)
			}
			reply("250 queued")
		case "RSET":
			reply(rsetReply)
		case "QUIT":
			reply("221 bye")
			return
		default: // MAIL, NOOP
			reply("250 ok")
		}
	}
}

func sendThroughFake(t *testing.T, rcptReply string) error {
	t.Helper()
	host, port := fakeSMTP(t, rcptReply)
	sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "noreply@shiptrip.test"}, nil)
	if err != nil {
		t.Fatalf("NewSMTPSender: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return sender.Send(ctx, EmailPayload{EventID: "evt-classify", To: "someone@example.com", Subject: "s", Body: "b"})
}

func TestSMTP5xxRejectionIsPermanentWithItsReplyCode(t *testing.T) {
	err := sendThroughFake(t, "550 5.1.1 no such mailbox")
	permanent, ok := AsPermanent(err)
	if !ok {
		t.Fatalf("550 reply: err = %v, want a PermanentError", err)
	}
	if permanent.Code != 550 {
		t.Fatalf("PermanentError.Code = %d, want 550", permanent.Code)
	}
}

func TestSMTP4xxAndTransportFailuresStayRetryable(t *testing.T) {
	err := sendThroughFake(t, "451 4.3.0 try again later")
	if err == nil {
		t.Fatal("451 reply: want an error")
	}
	if _, ok := AsPermanent(err); ok {
		t.Fatalf("451 reply classified permanent: %v", err)
	}

	// Nothing listening: a dial failure has no reply code and must be retried.
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	port, _ := strconv.Atoi(strings.TrimPrefix(ln.Addr().String(), "127.0.0.1:"))
	_ = ln.Close()
	sender, err := NewSMTPSender(SMTPConfig{Host: "127.0.0.1", Port: port, FromAddr: "noreply@shiptrip.test"}, nil)
	if err != nil {
		t.Fatalf("NewSMTPSender: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	err = sender.Send(ctx, EmailPayload{EventID: "evt-dial", To: "someone@example.com", Subject: "s", Body: "b"})
	if err == nil {
		t.Fatal("dial to a closed port: want an error")
	}
	if _, ok := AsPermanent(err); ok {
		t.Fatalf("dial failure classified permanent: %v", err)
	}
}

func TestSMTPAcceptedSendReturnsNil(t *testing.T) {
	if err := sendThroughFake(t, "250 recipient ok"); err != nil {
		t.Fatalf("accepted send returned %v", err)
	}
}

func TestAsPermanentSeesThroughWrapping(t *testing.T) {
	base := &PermanentError{Err: errors.New("x"), Code: 552}
	got, ok := AsPermanent(errors.Join(errors.New("context"), base))
	if !ok || got.Code != 552 {
		t.Fatalf("AsPermanent(wrapped) = %v, %v", got, ok)
	}
	if _, ok := AsPermanent(errors.New("plain")); ok {
		t.Fatal("a plain error must not be permanent")
	}
}

// A failure after the server accepted DATA (here the RSET go-mail sends next)
// must not be retried: the mail is already on its way, and a retry would be a
// second copy of the same message.
func TestSMTPErrorAfterAcceptedDataIsTreatedAsSent(t *testing.T) {
	var accepted atomic.Int32
	host, port := fakeSMTPWith(t, "250 recipient ok", "421 4.4.2 closing connection", &accepted)
	sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "noreply@shiptrip.test"}, discardLog())
	if err != nil {
		t.Fatalf("NewSMTPSender: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	err = sender.Send(ctx, EmailPayload{EventID: "evt-rset", To: "someone@example.com", Subject: "s", Body: "b"})
	if err != nil {
		t.Fatalf("send after accepted DATA returned %v, want nil (the mail was delivered)", err)
	}
	if got := accepted.Load(); got != 1 {
		t.Fatalf("server accepted %d messages, want 1", got)
	}
}

// Recipient addresses must never reach the logs. go-mail's SendError text
// lists "affected recipient(s): <address>" and the fake server echoes the
// address in its reply line, as real relays do; a transient failure repeats
// its log line on every sweeper retry.
func TestSendFailureLogsNeverNameTheRecipient(t *testing.T) {
	const rcpt = "private.person@example.com"
	for _, tc := range []struct {
		name, reply string
		wantCode    string
	}{
		{"transient 4xx", "451 4.2.2 <" + rcpt + ">: mailbox full", "smtp_code=451"},
		{"permanent 5xx", "550 5.1.1 <" + rcpt + ">: no such user", "smtp_code=550"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			log := slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
			host, port := fakeSMTP(t, tc.reply)
			sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "noreply@shiptrip.test"}, log)
			if err != nil {
				t.Fatalf("NewSMTPSender: %v", err)
			}
			c := NewConsumer(nil, ConsumerConfig{Sender: sender}, log)
			c.rdb = &fakeStream{}
			raw, _ := json.Marshal(EmailPayload{EventID: "evt-pii", To: rcpt, Subject: "Your code 123456", Body: "b", Kind: "verify"})
			c.handle(context.Background(), redisbus.StreamMessage{
				ID: sid(1), Values: map[string]any{"event_id": "evt-pii", "payload": string(raw)},
			})

			out := buf.String()
			if strings.Contains(out, rcpt) {
				t.Fatalf("log output names the recipient:\n%s", out)
			}
			if strings.Contains(out, "123456") {
				t.Fatalf("log output carries the subject:\n%s", out)
			}
			if !strings.Contains(out, tc.wantCode) || !strings.Contains(out, "smtp_host="+host) {
				t.Fatalf("log output lacks the reply code or relay host:\n%s", out)
			}
		})
	}
}

func TestSendFailureErrorTextIsLogSafe(t *testing.T) {
	const rcpt = "private.person@example.com"
	host, port := fakeSMTP(t, "451 4.2.2 <"+rcpt+">: mailbox full")
	sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "noreply@shiptrip.test"}, discardLog())
	if err != nil {
		t.Fatalf("NewSMTPSender: %v", err)
	}
	err = sender.Send(context.Background(), EmailPayload{EventID: "e", To: rcpt, Subject: "s", Body: "b"})
	if err == nil {
		t.Fatal("451 reply: want an error")
	}
	// The raw go-mail error does name the recipient; that is the leak.
	if raw := errors.Unwrap(err); raw == nil || !strings.Contains(raw.Error(), rcpt) {
		t.Fatalf("expected the wrapped go-mail error to carry the address (test premise), got %v", raw)
	}
	if strings.Contains(err.Error(), rcpt) {
		t.Fatalf("SendFailure.Error() names the recipient: %s", err)
	}
	for _, v := range SendFailureLogAttrs(err) {
		if s, ok := v.(string); ok && strings.Contains(s, rcpt) {
			t.Fatalf("SendFailureLogAttrs carries the recipient: %v", SendFailureLogAttrs(err))
		}
	}

	// An address that cannot even be parsed is quoted by go-mail's parser.
	err = sender.Send(context.Background(), EmailPayload{EventID: "e", To: "not an <address", Subject: "s", Body: "b"})
	if _, ok := AsPermanent(err); !ok || strings.Contains(err.Error(), "not an <address") {
		t.Fatalf("unparseable recipient: err = %v, want a permanent, address-free error", err)
	}
}

func TestSendFailureLogAttrsForOtherSenders(t *testing.T) {
	attrs := SendFailureLogAttrs(errors.New("rcpt someone@example.com refused"))
	for _, v := range attrs {
		if s, ok := v.(string); ok && strings.Contains(s, "@") {
			t.Fatalf("an unknown sender error was logged as text: %v", attrs)
		}
	}
	if got := SendFailureLogAttrs(context.DeadlineExceeded); got[1] != "timeout" {
		t.Fatalf("deadline attrs = %v", got)
	}
}

func discardLog() *slog.Logger { return slog.New(slog.DiscardHandler) }
