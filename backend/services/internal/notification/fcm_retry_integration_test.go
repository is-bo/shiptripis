//go:build integration

package notification

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

// itPartialSender reports every token as a transient failure on every call —
// the shape of a token FCM keeps rejecting with a non-permanent code.
type itPartialSender struct {
	mu    sync.Mutex
	calls int
}

func (s *itPartialSender) Send(_ context.Context, p FCMPayload) (SendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	indexes := make([]int, len(p.Tokens))
	for i := range indexes {
		indexes[i] = i
	}
	return SendResult{RetryTokenIndexes: indexes}, nil
}

func (s *itPartialSender) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

// TestFCMPartialRetryChainIsBounded: before the retry budget, a token that
// failed transiently on every try re-enqueued itself every grace period for
// ever. The chain must stop after maxPartialRetries re-enqueues, with every
// entry acked.
func TestFCMPartialRetryChainIsBounded(t *testing.T) {
	rdb, raw := itRedis(t)
	stream := itStream(t, raw)

	sender := &itPartialSender{}
	consumer := itNewConsumer(rdb, stream, sender)
	consumer.retryBase = 10 * time.Millisecond
	consumer.retryCeiling = 20 * time.Millisecond
	stopConsumer := itRunConsumer(t, consumer, false)
	defer stopConsumer()

	if _, err := rdb.XAddCapped(context.Background(), stream, 1000,
		itFCMEntry(t, itEventID(t, "partial"), 4201, []string{"tok-flaky"}),
	); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	want := int64(1 + maxPartialRetries)
	itWaitProcessed(t, raw, stream, "it-workers", want, 20*time.Second)
	// Give a runaway chain room to show itself before asserting it stopped.
	time.Sleep(time.Second)
	if n := itEntriesRead(t, raw, stream, "it-workers"); n != want {
		t.Fatalf("consumer read %d entries, want exactly %d (original + %d retries)", n, want, maxPartialRetries)
	}
	if n := sender.count(); n != int(want) {
		t.Fatalf("sender called %d times, want %d", n, want)
	}
}

// TestFCMEntryPastItsRetryWindowIsDropped: an entry older than MaxEntryAge is
// acked without a send, so a poison entry cannot be swept for ever.
func TestFCMEntryPastItsRetryWindowIsDropped(t *testing.T) {
	rdb, raw := itRedis(t)
	stream := itStream(t, raw)

	sender := &itSender{}
	consumer := itNewConsumer(rdb, stream, sender)
	stopConsumer := itRunConsumer(t, consumer, false)
	defer stopConsumer()

	// An explicit, ancient stream ID: Redis records it as the creation time.
	if err := raw.XAdd(context.Background(), &redis.XAddArgs{
		Stream: stream,
		ID:     "1000-1",
		Values: itFCMEntry(t, itEventID(t, "stale"), 4202, []string{"tok-stale"}),
	}).Err(); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	itWaitProcessed(t, raw, stream, "it-workers", 1, 10*time.Second)
	if n := sender.count(); n != 0 {
		t.Fatalf("sender pushed %d stale entries, want 0", n)
	}
}
