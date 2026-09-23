package notification

import "testing"

// The worker sleeps out a partial-retry backoff while it still owns the PEL
// entry. If that sleep plus the send budget could reach SweepMinIdle, the
// sweeper would reclaim the entry mid-wait and a second handler would push
// the same notification again.
func TestPartialRetryWaitStaysInsideTheSweeperIdleWindow(t *testing.T) {
	if retryCeiling+sendTimeout+ackTimeout >= SweepMinIdle {
		t.Fatalf("retryCeiling (%s) + sendTimeout (%s) + ackTimeout (%s) must stay below SweepMinIdle (%s)",
			retryCeiling, sendTimeout, ackTimeout, SweepMinIdle)
	}
	if maxPartialRetries < 1 {
		t.Fatalf("maxPartialRetries = %d; a transient token failure deserves at least one retry", maxPartialRetries)
	}
}

func TestRetryAttemptReadsOnlyAWellFormedCounter(t *testing.T) {
	cases := []struct {
		values map[string]any
		want   int
	}{
		{map[string]any{}, 0},                  // Django's original entry
		{map[string]any{"attempt": "3"}, 3},    // a worker re-enqueue
		{map[string]any{"attempt": "-2"}, 0},   // nonsense is attempt 0, not a drop
		{map[string]any{"attempt": "many"}, 0}, // likewise
		{map[string]any{"attempt": 4}, 0},      // go-redis always yields strings
	}
	for _, tc := range cases {
		if got := retryAttempt(tc.values); got != tc.want {
			t.Fatalf("retryAttempt(%v) = %d, want %d", tc.values, got, tc.want)
		}
	}
}
