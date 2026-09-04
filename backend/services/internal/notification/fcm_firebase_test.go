package notification

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
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
	return &firebaseSender{
		client:           fake,
		log:              discardLogger(),
		isPermanentToken: func(error) bool { return false },
	}
}

func samplePayload() FCMPayload {
	return FCMPayload{
		EventID:           "evt-1",
		UserID:            42,
		Tokens:            []string{"tokA", "tokB"},
		DeviceIDs:         []int64{101, 102},
		TokenFingerprints: []string{"fpA", "fpB"},
		Title:             "hi",
		Body:              "there",
		AndroidChannelID:  "messages",
		Data:              map[string]string{"route": "/chat/7"},
	}
}

func TestFirebaseSenderSend(t *testing.T) {
	ctx := context.Background()

	t.Run("empty token list is a no-op", func(t *testing.T) {
		fake := &fakeMulticaster{}
		s := newTestSender(fake)
		p := samplePayload()
		p.Tokens = nil
		if _, err := s.Send(ctx, p); err != nil {
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
		result, err := s.Send(ctx, samplePayload())
		if err != nil {
			t.Fatalf("Send = %v, want nil", err)
		}
		if len(result.SuccessfulDeviceIDs) != 2 {
			t.Fatalf("successful devices = %v, want [101 102]", result.SuccessfulDeviceIDs)
		}
		if len(result.SuccessfulTokenFingerprints) != 2 || result.SuccessfulTokenFingerprints[0] != "fpA" {
			t.Fatalf("successful fingerprints = %v, want [fpA fpB]", result.SuccessfulTokenFingerprints)
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
		if fake.gotMsg.Android == nil || fake.gotMsg.Android.Notification.ChannelID != "messages" {
			t.Fatalf("android config = %+v, want messages channel", fake.gotMsg.Android)
		}
	})

	t.Run("partial transient failure returns only its retry index", func(t *testing.T) {
		fake := &fakeMulticaster{resp: &messaging.BatchResponse{
			SuccessCount: 1,
			FailureCount: 1,
			Responses: []*messaging.SendResponse{
				{Success: true, MessageID: "m1"},
				{Success: false, Error: errors.New("token boom")},
			},
		}}
		s := newTestSender(fake)
		result, err := s.Send(ctx, samplePayload())
		if err != nil {
			t.Fatalf("Send = %v, want nil on partial failure", err)
		}
		if len(result.RetryTokenIndexes) != 1 || result.RetryTokenIndexes[0] != 1 {
			t.Fatalf("retry indexes = %v, want [1]", result.RetryTokenIndexes)
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
		_, err := s.Send(ctx, samplePayload())
		if err == nil || !strings.Contains(err.Error(), "all 2 tokens failed transiently") {
			t.Fatalf("err = %v, want transient all-failed error", err)
		}
		if !strings.Contains(err.Error(), "evt-1") {
			t.Fatalf("err = %v, want event id in message", err)
		}
	})

	t.Run("transport error returns error and surfaces event id", func(t *testing.T) {
		fake := &fakeMulticaster{err: errors.New("network down")}
		s := newTestSender(fake)
		_, err := s.Send(ctx, samplePayload())
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

	t.Run("permanently invalid tokens are reported and not retried", func(t *testing.T) {
		permanent := errors.New("unregistered")
		fake := &fakeMulticaster{resp: &messaging.BatchResponse{
			SuccessCount: 0,
			FailureCount: 2,
			Responses: []*messaging.SendResponse{
				{Success: false, Error: permanent},
				{Success: false, Error: permanent},
			},
		}}
		s := newTestSender(fake)
		s.isPermanentToken = func(err error) bool { return errors.Is(err, permanent) }
		result, err := s.Send(ctx, samplePayload())
		if err != nil {
			t.Fatalf("Send = %v, want nil for permanent failures", err)
		}
		if len(result.InvalidDeviceIDs) != 2 || result.InvalidDeviceIDs[0] != 101 || result.InvalidDeviceIDs[1] != 102 {
			t.Fatalf("invalid devices = %v, want [101 102]", result.InvalidDeviceIDs)
		}
		if len(result.InvalidTokenFingerprints) != 2 || result.InvalidTokenFingerprints[1] != "fpB" {
			t.Fatalf("invalid fingerprints = %v, want [fpA fpB]", result.InvalidTokenFingerprints)
		}
	})

	t.Run("per-token failures never log registration tokens", func(t *testing.T) {
		var logs bytes.Buffer
		fake := &fakeMulticaster{resp: &messaging.BatchResponse{
			SuccessCount: 1,
			FailureCount: 1,
			Responses: []*messaging.SendResponse{
				{Success: true, MessageID: "m1"},
				{Success: false, Error: errors.New("token boom")},
			},
		}}
		s := newTestSender(fake)
		s.log = slog.New(slog.NewTextHandler(&logs, nil))
		if _, err := s.Send(ctx, samplePayload()); err != nil {
			t.Fatalf("Send = %v, want nil", err)
		}
		if strings.Contains(logs.String(), "tokA") || strings.Contains(logs.String(), "tokB") {
			t.Fatalf("logs exposed an FCM registration token: %s", logs.String())
		}
	})
}

func TestTransientRetryPayload(t *testing.T) {
	payload, err := transientRetryPayload(samplePayload(), []int{1})
	if err != nil {
		t.Fatalf("transientRetryPayload = %v", err)
	}
	if len(payload.Tokens) != 1 || payload.Tokens[0] != "tokB" {
		t.Fatalf("retry tokens = %v, want [tokB]", payload.Tokens)
	}
	if len(payload.DeviceIDs) != 1 || payload.DeviceIDs[0] != 102 {
		t.Fatalf("retry device ids = %v, want [102]", payload.DeviceIDs)
	}
	if len(payload.TokenFingerprints) != 1 || payload.TokenFingerprints[0] != "fpB" {
		t.Fatalf("retry fingerprints = %v, want [fpB]", payload.TokenFingerprints)
	}
	if _, err := transientRetryPayload(samplePayload(), []int{2}); err == nil {
		t.Fatal("out-of-range retry index should fail")
	}
}

// firebaseSender must satisfy the FCMSender swap point.
func TestFirebaseSenderSatisfiesInterface(t *testing.T) {
	var _ FCMSender = (*firebaseSender)(nil)
}
