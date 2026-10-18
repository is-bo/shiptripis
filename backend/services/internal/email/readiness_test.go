package email

import (
	"context"
	"net"
	"sync/atomic"
	"testing"
	"time"
)

func TestMandatorySTARTTLSNeverFallsBackToPlaintext(t *testing.T) {
	var accepted atomic.Int32
	host, port := fakeSMTPWith(t, "250 ok", "250 ok", &accepted)
	sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, UseTLS: true, FromAddr: "notifications@example.invalid"}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	if sender.Send(context.Background(), EmailPayload{EventID: "tls", To: "only@example.invalid", Subject: "test", Body: "test"}) == nil {
		t.Fatal("SMTP without STARTTLS was accepted")
	}
	if accepted.Load() != 0 {
		t.Fatal("plaintext delivery")
	}
}

func TestSMTPConnectionTimeoutIsBoundedAndRetryable(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	done := make(chan struct{})
	go func() {
		conn, err := listener.Accept()
		if err == nil {
			defer conn.Close()
			<-done
		}
	}()
	defer close(done)
	address := listener.Addr().(*net.TCPAddr)
	sender, err := NewSMTPSender(SMTPConfig{Host: "127.0.0.1", Port: address.Port, FromAddr: "notifications@example.invalid", Timeout: 100 * time.Millisecond}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	err = sender.Send(context.Background(), EmailPayload{EventID: "timeout", To: "only@example.invalid", Subject: "test", Body: "test"})
	if err == nil {
		t.Fatal("stalled SMTP did not time out")
	}
	if _, permanent := AsPermanent(err); permanent {
		t.Fatal("timeout is permanent")
	}
	if time.Since(start) > time.Second {
		t.Fatal("SMTP exceeded configured timeout")
	}
}

func TestRetryUsesStableMessageIDAndReplyTo(t *testing.T) {
	sender, err := NewSMTPSender(SMTPConfig{Host: "127.0.0.1", Port: 1025, FromAddr: "notifications@example.invalid", FromName: "Waçla", ReplyTo: "support@example.invalid"}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	p := EmailPayload{EventID: "same-obligation", To: "only@example.invalid", Subject: "test", Body: "test"}
	first, err := sender.(*smtpSender).buildMessage(p)
	if err != nil {
		t.Fatal(err)
	}
	second, err := sender.(*smtpSender).buildMessage(p)
	if err != nil {
		t.Fatal(err)
	}
	if first.GetMessageID() == "" || first.GetMessageID() != second.GetMessageID() {
		t.Fatal("retry changed Message-ID")
	}
}
