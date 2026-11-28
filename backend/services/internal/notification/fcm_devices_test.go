package notification

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
)

// N1 Astra round 4: a push queued for account A must not reach a phone that
// was signed out of A, or that B now holds, while the entry waited.

type fcmRecordingSender struct {
	mu   sync.Mutex
	sent []FCMPayload
}

func (s *fcmRecordingSender) Send(_ context.Context, p FCMPayload) (SendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sent = append(s.sent, p)
	return SendResult{SuccessfulDeviceIDs: p.DeviceIDs, SuccessfulTokenFingerprints: p.TokenFingerprints}, nil
}

func (s *fcmRecordingSender) payloads() []FCMPayload {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]FCMPayload(nil), s.sent...)
}

func fcmTwoDeviceEntry(t *testing.T, id string) redisbus.StreamMessage {
	t.Helper()
	raw, err := json.Marshal(FCMPayload{
		EventID: "evt-devices", UserID: 7,
		Tokens:            []string{"token-a", "token-b"},
		DeviceIDs:         []int64{1, 2},
		TokenFingerprints: []string{strings.Repeat("a", 64), strings.Repeat("b", 64)},
		SessionIDs:        []string{"sign-in-a", "sign-in-b"},
		Title:             "t", Body: "b",
	})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return redisbus.StreamMessage{ID: id, Values: map[string]any{
		"event_id": "evt-devices", "user_id": "7", "payload": string(raw),
	}}
}

// runOne feeds one entry through Run until until() holds, then stops it.
func runOne(t *testing.T, devices DeviceRegistry, until func(rdb *fcmFakeStream) bool) (*fcmFakeStream, *fcmRecordingSender) {
	t.Helper()
	rdb := &fcmFakeStream{reads: []fcmFakeRead{{msgs: []redisbus.StreamMessage{fcmTwoDeviceEntry(t, sid(1))}}}}
	sender := &fcmRecordingSender{}
	c := fcmTestConsumerWith(rdb, sender, devices)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- c.Run(ctx) }()
	fcmWaitUntil(t, "the entry to be handled", func() bool { return until(rdb) })
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("Run returned %v", err)
	}
	return rdb, sender
}

func acked(rdb *fcmFakeStream) bool { _, _, a := rdb.snapshot(); return len(a) == 1 }

func TestFCMDropsAPushNoneOfWhosePhonesIsStillTheRecipients(t *testing.T) {
	devices := &fcmScriptedDevices{bound: map[int64]bool{}}
	_, sender := runOne(t, devices, acked)

	if sent := sender.payloads(); len(sent) != 0 {
		t.Fatalf("sent %d pushes to phones the recipient no longer holds", len(sent))
	}
	if len(devices.asked) != 1 || devices.asked[0] != 7 {
		t.Fatalf("asked about users %v, want [7]", devices.asked)
	}
}

func TestFCMSendsOnlyToThePhonesStillBound(t *testing.T) {
	_, sender := runOne(t, &fcmScriptedDevices{bound: map[int64]bool{2: true}}, acked)

	sent := sender.payloads()
	if len(sent) != 1 {
		t.Fatalf("sent %d pushes, want 1", len(sent))
	}
	if got := sent[0]; len(got.Tokens) != 1 || got.Tokens[0] != "token-b" ||
		got.DeviceIDs[0] != 2 || got.TokenFingerprints[0] != strings.Repeat("b", 64) {
		t.Fatalf("sent %+v, want only device 2", got)
	}
}

func TestFCMLeavesThePushPendingWhenThePhonesCannotBeChecked(t *testing.T) {
	devices := &fcmScriptedDevices{err: errors.New("database unavailable")}
	rdb, sender := runOne(t, devices, func(*fcmFakeStream) bool {
		devices.mu.Lock()
		defer devices.mu.Unlock()
		return len(devices.asked) == 1
	})
	time.Sleep(20 * time.Millisecond)

	if len(sender.payloads()) != 0 {
		t.Fatal("sent without checking the phones")
	}
	if acked(rdb) {
		t.Fatal("acked: the sweeper could no longer retry the push")
	}
}

// TestStillBoundQueryMatchesTheSchema guards the query against the table
// Django owns: CI has no Postgres for this package, and a renamed column would
// otherwise only show as every push failing its device check.
func TestStillBoundQueryMatchesTheSchema(t *testing.T) {
	raw, err := os.ReadFile("../../../contracts/sql/schema.sql")
	if err != nil {
		t.Fatalf("read schema: %v", err)
	}
	table := regexp.MustCompile(`(?s)CREATE TABLE public\.notification_push_device \((.*?)\n\);`).FindSubmatch(raw)
	if table == nil {
		t.Fatal("schema.sql has no notification_push_device table")
	}
	for _, column := range []string{"id bigint", "user_id bigint", "active boolean", "token_fingerprint character varying", "session_id uuid"} {
		if !strings.Contains(string(table[1]), "    "+column) {
			t.Errorf("notification_push_device has no %q column", column)
		}
	}
	for _, name := range []string{"notification_push_device", "user_id", "active", "token_fingerprint", "session_id", "id = ANY"} {
		if !strings.Contains(stillBoundQuery, name) {
			t.Errorf("stillBoundQuery does not name %q", name)
		}
	}
}

// fcmRetryOnceSender fails device 2 transiently on its first send, the
// partial failure the worker re-enqueues as a retry, and records each send.
type fcmRetryOnceSender struct {
	mu   sync.Mutex
	sent []FCMPayload
}

func (s *fcmRetryOnceSender) Send(_ context.Context, p FCMPayload) (SendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sent = append(s.sent, p)
	if len(s.sent) == 1 {
		return SendResult{SuccessfulDeviceIDs: p.DeviceIDs[:1], SuccessfulTokenFingerprints: p.TokenFingerprints[:1], RetryTokenIndexes: []int{1}}, nil
	}
	return SendResult{SuccessfulDeviceIDs: p.DeviceIDs, SuccessfulTokenFingerprints: p.TokenFingerprints}, nil
}

// N1, N-F: a retry is checked again before it is sent, with the sign-in the
// push was queued for. Device 2 is rebound to another sign-in between the
// first send and the retry, so the retry is dropped.
func TestFCMChecksARetryAgainWithItsSignIn(t *testing.T) {
	rdb := &fcmFakeStream{}
	sender := &fcmRetryOnceSender{}
	devices := &fcmScriptedDevices{bound: map[int64]bool{1: true, 2: true}}
	c := fcmTestConsumerWith(rdb, sender, devices)
	c.retryBase, c.retryCeiling = time.Millisecond, time.Millisecond

	c.handle(context.Background(), fcmTwoDeviceEntry(t, sid(1)), time.Now())
	var retry map[string]any
	for _, fields := range rdb.addedFields {
		if _, ok := fields["attempt"]; ok {
			retry = fields
		}
	}
	if retry == nil {
		t.Fatal("the transient failure was not re-enqueued")
	}
	values := make(map[string]any, len(retry))
	for key, value := range retry {
		values[key] = fmt.Sprint(value) // as Redis returns every field
	}
	devices.mu.Lock()
	devices.bound[2] = false
	devices.mu.Unlock()

	c.handle(context.Background(), redisbus.StreamMessage{ID: sid(2), Values: values}, time.Now())

	if len(sender.sent) != 1 {
		t.Fatalf("sent %d pushes, want only the first", len(sender.sent))
	}
	if len(devices.payloads) != 2 {
		t.Fatalf("checked the phones %d times, want 2", len(devices.payloads))
	}
	if got := devices.payloads[1]; len(got.DeviceIDs) != 1 || got.DeviceIDs[0] != 2 ||
		len(got.SessionIDs) != 1 || got.SessionIDs[0] != "sign-in-b" {
		t.Fatalf("the retry was checked as %+v, want device 2 with sign-in-b", got)
	}
	if _, _, acked := rdb.snapshot(); len(acked) != 2 || acked[1] != sid(2) {
		t.Fatalf("acked %v, want the dropped retry acked too", acked)
	}
}
