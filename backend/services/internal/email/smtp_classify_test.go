package email

import (
	"bufio"
	"context"
	"errors"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

// fakeSMTP is a minimal line-level SMTP server that answers RCPT TO with a
// fixed reply, so the sender's retry classification is exercised against a
// real go-mail conversation rather than a hand-built error value.
func fakeSMTP(t *testing.T, rcptReply string) (host string, port int) {
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
			go serveFakeSMTP(conn, rcptReply)
		}
	}()
	addr := ln.Addr().(*net.TCPAddr)
	return addr.IP.String(), addr.Port
}

func serveFakeSMTP(conn net.Conn, rcptReply string) {
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
			reply("250 queued")
		case "QUIT":
			reply("221 bye")
			return
		default: // MAIL, NOOP, RSET
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
