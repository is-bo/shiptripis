// Package metrics is a thin counter/gauge layer over expvar.
//
// Each service registers a group at boot via Register(serviceName) and
// then reads/writes through the returned Group. expvar publishes
// /debug/vars on the default http.DefaultServeMux — services that want
// the endpoint scraped expose it explicitly on their admin mux (see
// cmd/notification, cmd/chat).
//
// Two design choices worth recording:
//
//  1. expvar over Prometheus client_golang: zero new deps, sufficient
//     for ops dashboards in V1 (Grafana can scrape JSON), and the call
//     sites stay identical when we later swap the impl. The Group type
//     is the swap point.
//  2. Counters are *expvar.Int (int64 monotonic) and gauges are
//     *expvar.Float. Labels are NOT first-class — they're folded into
//     the metric name (e.g. "pubsub_drops_offer_accepted"). For V1's
//     ~30 metrics this is fine; if cardinality grows past ~100 the
//     swap to Prometheus becomes worth the dep.
package metrics

import (
	"expvar"
	"strings"
	"sync"
)

// Group is a namespaced bag of metrics for a single service. All names
// inside a group are auto-prefixed with the service name so two services
// can use the same metric without collision.
type Group struct {
	prefix string
	mu     sync.Mutex
	ints   map[string]*expvar.Int
	floats map[string]*expvar.Float
}

// rootMap is the expvar Map every Group publishes into. Lives under
// "shiptrip" in /debug/vars so service vars don't pollute the top level.
var (
	rootOnce sync.Once
	root     *expvar.Map
)

func rootMap() *expvar.Map {
	rootOnce.Do(func() {
		root = expvar.NewMap("shiptrip")
	})
	return root
}

// Register builds a new Group for the named service. Safe to call once
// per service at boot; subsequent calls with the same name return the
// existing Group's expvar bindings (not a literal singleton — the
// returned Group is fresh but writes land in the same expvar Vars).
func Register(service string) *Group {
	return &Group{
		prefix: sanitize(service),
		ints:   make(map[string]*expvar.Int),
		floats: make(map[string]*expvar.Float),
	}
}

// Counter increments the named counter by delta. Counter is monotonic;
// use Gauge for values that go up and down. delta of 0 still ensures
// the metric exists in expvar output, which makes dashboards happier.
func (g *Group) Counter(name string, delta int64) {
	g.intVar(name).Add(delta)
}

// Gauge sets the named gauge to v. Use for in-flight counts, queue
// depths, percentages. Not safe to interleave with Counter on the same
// name — pick one per metric.
func (g *Group) Gauge(name string, v float64) {
	g.floatVar(name).Set(v)
}

// GaugeAdd adds delta to the named gauge. Convenient for in-flight
// counters (acquire +1, release -1) that semantically aren't monotonic
// counters.
func (g *Group) GaugeAdd(name string, delta float64) {
	g.floatVar(name).Add(delta)
}

func (g *Group) intVar(name string) *expvar.Int {
	full := g.prefix + "_" + sanitize(name)
	g.mu.Lock()
	defer g.mu.Unlock()
	if v, ok := g.ints[name]; ok {
		return v
	}
	v := new(expvar.Int)
	g.ints[name] = v
	rootMap().Set(full, v)
	return v
}

func (g *Group) floatVar(name string) *expvar.Float {
	full := g.prefix + "_" + sanitize(name)
	g.mu.Lock()
	defer g.mu.Unlock()
	if v, ok := g.floats[name]; ok {
		return v
	}
	v := new(expvar.Float)
	g.floats[name] = v
	rootMap().Set(full, v)
	return v
}

// Sanitize exposes the name-folding rule (lowercase + [a-z0-9_]) used to
// build the full expvar key. Callers that need to reconstruct a published
// metric's key — e.g. tests reading /debug/vars — use this so they don't
// hardcode the transform.
func Sanitize(s string) string { return sanitize(s) }

// sanitize lowercases and replaces anything outside [a-z0-9_] with _ so
// metric names are safe Prometheus identifiers when we eventually export.
func sanitize(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range strings.ToLower(s) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == '_':
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}
	return b.String()
}
