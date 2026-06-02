package redisbus

import (
	"encoding/json"
	"expvar"
	"io"
	"log/slog"
	"strconv"
	"testing"

	"shiptrip/pkg/metrics"
)

// newDropTestSub builds a Subscription with only the fields recordDrop
// touches (log + metrics). recordDrop never reads ps/out/stop/done, so a
// bare struct is enough to exercise the drop-accounting path without a
// live Redis connection.
func newDropTestSub(m *metrics.Group) *Subscription {
	return &Subscription{
		log:     slog.New(slog.NewTextHandler(io.Discard, nil)),
		metrics: m,
	}
}

func readInt(t *testing.T, full string) int64 {
	t.Helper()
	v := expvar.Get("shiptrip")
	m, ok := v.(*expvar.Map)
	if !ok {
		t.Fatalf("shiptrip expvar is %T, want *expvar.Map", v)
	}
	got := m.Get(full)
	if got == nil {
		t.Fatalf("expvar %q not published", full)
	}
	iv, ok := got.(*expvar.Int)
	if !ok {
		t.Fatalf("expvar %q is %T, want *expvar.Int", full, got)
	}
	n, err := strconv.ParseInt(iv.String(), 10, 64)
	if err != nil {
		t.Fatalf("parse %q: %v", full, err)
	}
	return n
}

func TestRecordDropIncrementsTotalAndPerChannel(t *testing.T) {
	m := metrics.Register("redisbus-drop-a")
	sub := newDropTestSub(m)

	payload := []byte(`{"event_id":"evt-42","ts":"2026-06-01T00:00:00Z","targets":[1,2]}`)
	sub.recordDrop("offer.accepted", payload)
	sub.recordDrop("offer.accepted", payload)

	if got := readInt(t, "redisbus_drop_a_pubsub_drops_total"); got != 2 {
		t.Errorf("pubsub_drops_total = %d, want 2", got)
	}
	// Channel folded into the metric name and sanitized (. → _).
	if got := readInt(t, "redisbus_drop_a_pubsub_drops_offer_accepted"); got != 2 {
		t.Errorf("per-channel drop = %d, want 2", got)
	}
}

func TestRecordDropSeparatesChannels(t *testing.T) {
	m := metrics.Register("redisbus-drop-b")
	sub := newDropTestSub(m)

	sub.recordDrop("trip.created", []byte(`{"event_id":"a"}`))
	sub.recordDrop("parcel.created", []byte(`{"event_id":"b"}`))
	sub.recordDrop("parcel.created", []byte(`{"event_id":"c"}`))

	if got := readInt(t, "redisbus_drop_b_pubsub_drops_total"); got != 3 {
		t.Errorf("total = %d, want 3", got)
	}
	if got := readInt(t, "redisbus_drop_b_pubsub_drops_trip_created"); got != 1 {
		t.Errorf("trip.created drop = %d, want 1", got)
	}
	if got := readInt(t, "redisbus_drop_b_pubsub_drops_parcel_created"); got != 2 {
		t.Errorf("parcel.created drop = %d, want 2", got)
	}
}

func TestRecordDropToleratesUnparseablePayload(t *testing.T) {
	m := metrics.Register("redisbus-drop-c")
	sub := newDropTestSub(m)

	// A non-JSON or partial payload must not panic — event_id is simply
	// absent in the log line; the counters still move (the drop happened).
	sub.recordDrop("kyc.status_changed", []byte("not json at all"))
	sub.recordDrop("kyc.status_changed", nil)

	if got := readInt(t, "redisbus_drop_c_pubsub_drops_total"); got != 2 {
		t.Errorf("total = %d, want 2", got)
	}
}

func TestRecordDropNilMetricsIsSafe(t *testing.T) {
	// Tests pass Metrics: nil; recordDrop must not panic when metrics is nil.
	sub := newDropTestSub(nil)
	sub.recordDrop("offer.created", []byte(`{"event_id":"x"}`))
}

func TestPubsubEventIDUnmarshal(t *testing.T) {
	// recordDrop best-effort-decodes event_id out of the full envelope so
	// G6b can correlate the loss. Verify the tagged subset binds correctly
	// and ignores the rest of the payload.
	var env pubsubEventID
	if err := json.Unmarshal([]byte(`{"event_id":"evt-1","ts":"t","targets":[7],"match_id":9}`), &env); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if env.EventID != "evt-1" {
		t.Errorf("event_id = %q, want evt-1", env.EventID)
	}
}
