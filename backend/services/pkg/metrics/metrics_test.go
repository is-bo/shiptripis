package metrics

import (
	"expvar"
	"strconv"
	"testing"
)

// readInt pulls the current value of a published expvar.Int by its full
// (prefixed, sanitized) name out of the shared "shiptrip" map.
func readInt(t *testing.T, full string) int64 {
	t.Helper()
	v := rootMap().Get(full)
	if v == nil {
		t.Fatalf("expvar %q not published", full)
	}
	iv, ok := v.(*expvar.Int)
	if !ok {
		t.Fatalf("expvar %q is %T, want *expvar.Int", full, v)
	}
	n, err := strconv.ParseInt(iv.String(), 10, 64)
	if err != nil {
		t.Fatalf("parse %q value %q: %v", full, iv.String(), err)
	}
	return n
}

func readFloat(t *testing.T, full string) float64 {
	t.Helper()
	v := rootMap().Get(full)
	if v == nil {
		t.Fatalf("expvar %q not published", full)
	}
	fv, ok := v.(*expvar.Float)
	if !ok {
		t.Fatalf("expvar %q is %T, want *expvar.Float", full, v)
	}
	f, err := strconv.ParseFloat(fv.String(), 64)
	if err != nil {
		t.Fatalf("parse %q value %q: %v", full, fv.String(), err)
	}
	return f
}

func TestCounterIsMonotonicAndPrefixed(t *testing.T) {
	g := Register("notif-test-counter")
	g.Counter("events_delivered_total", 1)
	g.Counter("events_delivered_total", 2)

	// Prefix sanitized: "notif-test-counter" → "notif_test_counter".
	if got := readInt(t, "notif_test_counter_events_delivered_total"); got != 3 {
		t.Errorf("counter = %d, want 3", got)
	}
}

func TestCounterZeroDeltaStillPublishes(t *testing.T) {
	g := Register("svc_zero")
	// A 0 delta should still create the var so dashboards see it exist.
	g.Counter("idle_metric", 0)
	if got := readInt(t, "svc_zero_idle_metric"); got != 0 {
		t.Errorf("counter = %d, want 0", got)
	}
}

func TestGaugeSetAndAdd(t *testing.T) {
	g := Register("svc_gauge")
	g.Gauge("in_flight", 5)
	if got := readFloat(t, "svc_gauge_in_flight"); got != 5 {
		t.Errorf("gauge = %v, want 5", got)
	}
	g.GaugeAdd("in_flight", 2)
	g.GaugeAdd("in_flight", -3)
	if got := readFloat(t, "svc_gauge_in_flight"); got != 4 {
		t.Errorf("gauge after add = %v, want 4", got)
	}
}

func TestCounterReusesSameVar(t *testing.T) {
	g := Register("svc_reuse")
	g.Counter("hits", 1)
	g.Counter("hits", 1)
	// Same name must resolve to one var (the map cache), not two.
	if len(g.ints) != 1 {
		t.Errorf("ints map has %d entries, want 1", len(g.ints))
	}
	if got := readInt(t, "svc_reuse_hits"); got != 2 {
		t.Errorf("counter = %d, want 2", got)
	}
}

func TestSanitize(t *testing.T) {
	cases := map[string]string{
		"pubsub_drops_offer.accepted": "pubsub_drops_offer_accepted",
		"UPPER_Case":                  "upper_case",
		"with spaces":                 "with_spaces",
		"trip.created":                "trip_created",
		"already_ok_123":              "already_ok_123",
		"weird/chars:here":            "weird_chars_here",
		"":                            "",
	}
	for in, want := range cases {
		if got := sanitize(in); got != want {
			t.Errorf("sanitize(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFoldedChannelLabelNames(t *testing.T) {
	// pubsub_drops_<channel> is how redisbus folds the channel into the
	// metric name. Verify a dotted channel folds to a valid identifier.
	g := Register("svc_folded")
	g.Counter("pubsub_drops_"+"offer.accepted", 1)
	if got := readInt(t, "svc_folded_pubsub_drops_offer_accepted"); got != 1 {
		t.Errorf("folded counter = %d, want 1", got)
	}
}
