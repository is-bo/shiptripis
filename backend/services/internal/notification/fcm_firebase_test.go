package notification

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"firebase.google.com/go/v4/messaging"
)

// ── NewFirebaseSender: fail-loud at boot (CLAUDE.md §9) ──────────────────────

func TestNewFirebaseSenderValidation(t *testing.T) {
	ctx := context.Background()

	t.Run("empty credentials path errors", func(t *testing.T) {
		_, err := NewFirebaseSender(ctx, "proj", "", nil)
		if err == nil || !strings.Contains(err.Error(), "credentials path is required") {
			t.Fatalf("err = %v, want 'credentials path is required'", err)
		}
	})

	t.Run("unreadable credentials file errors", func(t *testing.T) {
		_, err := NewFirebaseSender(ctx, "proj", "/nonexistent/does-not-exist.json", nil)
		if err == nil {
			t.Fatal("expected error on unreadable credentials file")
		}
		// firebase.NewApp defers file read to first use, so the failure may
		// surface either at NewApp or app.Messaging — either way it must be
		// a non-nil error wrapped with our fcm: prefix.
		if !strings.Contains(err.Error(), "fcm:") {
			t.Fatalf("err = %v, want fcm:-prefixed", err)
		}
	})

	t.Run("invalid JSON credentials errors", func(t *testing.T) {
		dir := t.TempDir()
		bad := filepath.Join(dir, "creds.json")
		if err := os.WriteFile(bad, []byte("{not valid service account json"), 0o600); err != nil {
			t.Fatalf("write temp creds: %v", err)
		}
		_, err := NewFirebaseSender(ctx, "proj", bad, nil)
		if err == nil {
			t.Fatal("expected error on invalid credentials JSON")
		}
		if !strings.Contains(err.Error(), "fcm:") {
			t.Fatalf("err = %v, want fcm:-prefixed", err)
		}
	})
}

// ── Send: batch-response branch semantics ───────────────────────────────────

// fakeMulticaster drives firebaseSender.Send without a live FCM project.
type fakeMulticaster struct {
	resp   *messaging.BatchResponse
	err    error
	called int
	gotMsg *messaging.MulticastMessage
}

func (f *fakeMulticaster) SendEachForMulticast(_ context.Context, m *messaging.MulticastMessage) (*messaging.BatchResponse, error) {
	f.called++
	f.gotMsg = m
	return f.resp, f.err
}

func newTestSender(fake *fakeMulticaster) *firebaseSender {
	return &firebaseSender{client: fake, log: discardLogger()}
}

func samplePayload() FCMPayload {
	return FCMPayload{
		EventID: "evt-1",
		UserID:  42,
		Tokens:  []string{"tokA", "tokB"},
		Title:   "hi",
		Body:    "there",
		Data:    map[string]string{"route": "/chat/7"},
	}
}

func TestFirebaseSenderSend(t *testing.T) {
	ctx := context.Background()

	t.Run("empty token list is a no-op", func(t *testing.T) {
		fake := &fakeMulticaster{}
		s := newTestSender(fake)
		p := samplePayload()
		p.Tokens = nil
		if err := s.Send(ctx, p); err != nil {
			t.Fatalf("Send = %v, want nil", err)
		}
		if fake.called != 0 {
			t.Fatalf("multicast called %d times, want 0 for empty tokens", fake.called)
		}
	})

	t.Run("all tokens succeed returns nil", func(t *testing.T) {
		fake := &fakeMulticaster{resp: &messaging.BatchResponse{
			SuccessCount: 2,
			FailureCount: 0,
			Responses: []*messaging.SendResponse{
				{Success: true, MessageID: "m1"},
				{Success: true, MessageID: "m2"},
			},
		}}
		s := newTestSender(fake)
		if err := s.Send(ctx, samplePayload()); err != nil {
			t.Fatalf("Send = %v, want nil", err)
		}
		if fake.called != 1 {
			t.Fatalf("multicast called %d times, want 1", fake.called)
		}
		// Payload fields must flow through to the multicast message.
		if fake.gotMsg == nil || len(fake.gotMsg.Tokens) != 2 {
			t.Fatalf("message tokens = %+v, want 2", fake.gotMsg)
		}
		if fake.gotMsg.Notification == nil || fake.gotMsg.Notification.Title != "hi" {
			t.Fatalf("notification = %+v, want title 'hi'", fake.gotMsg.Notification)
		}
		if fake.gotMsg.Data["route"] != "/chat/7" {
			t.Fatalf("data = %+v, want route '/chat/7'", fake.gotMsg.Data)
		}
	})

	t.Run("partial failure returns nil (no full-batch resend)", func(t *testing.T) {
		fake := &fakeMulticaster{resp: &messaging.BatchResponse{
			SuccessCount: 1,
			FailureCount: 1,
			Responses: []*messaging.SendResponse{
				{Success: true, MessageID: "m1"},
				{Success: false, Error: errors.New("token boom")},
			},
		}}
		s := newTestSender(fake)
		if err := s.Send(ctx, samplePayload()); err != nil {
			t.Fatalf("Send = %v, want nil on partial failure", err)
		}
	})

	t.Run("all tokens fail returns error (kept in PEL for sweep)", func(t *testing.T) {
		fake := &fakeMulticaster{resp: &messaging.BatchResponse{
			SuccessCount: 0,
			FailureCount: 2,
			Responses: []*messaging.SendResponse{
				{Success: false, Error: errors.New("boom1")},
				{Success: false, Error: errors.New("boom2")},
			},
		}}
		s := newTestSender(fake)
		err := s.Send(ctx, samplePayload())
		if err == nil || !strings.Contains(err.Error(), "all 2 tokens failed") {
			t.Fatalf("err = %v, want 'all 2 tokens failed'", err)
		}
		if !strings.Contains(err.Error(), "evt-1") {
			t.Fatalf("err = %v, want event id in message", err)
		}
	})

	t.Run("transport error returns error and surfaces event id", func(t *testing.T) {
		fake := &fakeMulticaster{err: errors.New("network down")}
		s := newTestSender(fake)
		err := s.Send(ctx, samplePayload())
		if err == nil || !strings.Contains(err.Error(), "multicast send") {
			t.Fatalf("err = %v, want 'multicast send'", err)
		}
		if !strings.Contains(err.Error(), "network down") {
			t.Fatalf("err = %v, want wrapped transport error", err)
		}
		if !strings.Contains(err.Error(), "evt-1") {
			t.Fatalf("err = %v, want event id in message", err)
		}
	})
}

// firebaseSender must satisfy the FCMSender swap point.
func TestFirebaseSenderSatisfiesInterface(t *testing.T) {
	var _ FCMSender = (*firebaseSender)(nil)
}
