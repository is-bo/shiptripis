package chat

import (
	"context"
	"errors"
	"expvar"
	"io"
	"log/slog"
	"strconv"
	"sync/atomic"
	"testing"
	"time"

	"shiptrip/pkg/metrics"
)

// flakyExpirer fails its first failFirst SetEX calls, then succeeds.
type flakyExpirer struct {
	failFirst int
	attempts  atomic.Int32
}

func (f *flakyExpirer) SetEX(_ context.Context, _ string, _ any, _ time.Duration) error {
	if int(f.attempts.Add(1)) <= f.failFirst {
		return errors.New("redis blip")
	}
	return nil
}

type recordingExecer struct {
	ran atomic.Bool
	err error
}

func (e *recordingExecer) exec(_ context.Context, _ string) error {
	e.ran.Store(true)
	return e.err
}

func discardLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

// readCounter reads a published expvar.Int by its full (prefixed) name.
// Returns 0 if never published (a 0-delta counter is never created).
func readCounter(service, name string) int64 {
	full := metrics.Sanitize(service) + "_" + metrics.Sanitize(name)
	root, ok := expvar.Get("shiptrip").(*expvar.Map)
	if !ok {
		return 0
	}
	v := root.Get(full)
	if v == nil {
		return 0
	}
	n, _ := strconv.ParseInt(v.(*expvar.Int).String(), 10, 64)
	return n
}

func TestDBReceiptStore_SetEXRetrySucceedsSecondTry(t *testing.T) {
	const svc = "chat_receipt_retry_ok"
	exp := &flakyExpirer{failFirst: 1}
	ex := &recordingExecer{}
	s := &dbReceiptStore{rdb: exp, exec: ex, log: discardLogger(), metrics: metrics.Register(svc)}

	if err := s.MarkDelivered(context.Background(), "evt-retry", 42); err != nil {
		t.Fatalf("MarkDelivered = %v, want nil", err)
	}
	if got := exp.attempts.Load(); got != 2 {
		t.Errorf("SetEX attempts = %d, want 2", got)
	}
	if got := readCounter(svc, "delivered_setex_failures_total"); got != 1 {
		t.Errorf("setex_failures_total = %d, want 1", got)
	}
	if got := readCounter(svc, "delivered_setex_failures_final_total"); got != 0 {
		t.Errorf("setex_failures_final_total = %d, want 0", got)
	}
	if !ex.ran.Load() {
		t.Error("UPDATE did not run after SetEX recovered")
	}
}

func TestDBReceiptStore_BothAttemptsFailUpdateStillRuns(t *testing.T) {
	const svc = "chat_receipt_retry_fail"
	exp := &flakyExpirer{failFirst: 2}
	ex := &recordingExecer{}
	s := &dbReceiptStore{rdb: exp, exec: ex, log: discardLogger(), metrics: metrics.Register(svc)}

	if err := s.MarkDelivered(context.Background(), "evt-both-fail", 42); err != nil {
		t.Fatalf("MarkDelivered = %v, want nil (UPDATE succeeded)", err)
	}
	if got := readCounter(svc, "delivered_setex_failures_final_total"); got != 1 {
		t.Errorf("setex_failures_final_total = %d, want 1", got)
	}
	if !ex.ran.Load() {
		t.Error("UPDATE must run even when both SetEX attempts fail")
	}
}

func TestDBReceiptStore_CtxCancelledDuringRetrySkipsUpdate(t *testing.T) {
	const svc = "chat_receipt_retry_cancel"
	exp := &flakyExpirer{failFirst: 1}
	ex := &recordingExecer{}
	s := &dbReceiptStore{rdb: exp, exec: ex, log: discardLogger(), metrics: metrics.Register(svc)}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if err := s.MarkDelivered(ctx, "evt-cancel", 42); !errors.Is(err, context.Canceled) {
		t.Fatalf("MarkDelivered err = %v, want context.Canceled", err)
	}
	if got := exp.attempts.Load(); got != 1 {
		t.Errorf("SetEX attempts = %d, want 1 (retry skipped)", got)
	}
	if ex.ran.Load() {
		t.Error("UPDATE must NOT run when ctx cancelled during retry backoff")
	}
}

func TestDBReceiptStore_UpdateErrorIsMeteredAndReturned(t *testing.T) {
	const svc = "chat_receipt_update_err"
	exp := &flakyExpirer{}                                       // SetEX succeeds
	ex := &recordingExecer{err: errors.New("postgres exploded")} // UPDATE fails
	s := &dbReceiptStore{rdb: exp, exec: ex, log: discardLogger(), metrics: metrics.Register(svc)}

	if err := s.MarkDelivered(context.Background(), "evt-upd-fail", 42); err == nil {
		t.Fatal("MarkDelivered = nil, want UPDATE error propagated")
	}
	if got := readCounter(svc, "receipt_update_failures_total"); got != 1 {
		t.Errorf("receipt_update_failures_total = %d, want 1", got)
	}
}
