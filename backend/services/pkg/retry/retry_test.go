package retry

import (
	"testing"
	"time"
)

func TestBackoffGrowsCapsAndStaysWithinJitterBounds(t *testing.T) {
	base, ceiling := 5*time.Second, 30*time.Second
	cases := []struct {
		attempt int
		full    time.Duration
	}{
		{1, 5 * time.Second},
		{2, 10 * time.Second},
		{3, 20 * time.Second},
		{4, 30 * time.Second},
		{5, 30 * time.Second},
		{60, 30 * time.Second}, // no overflow on large attempt numbers
	}
	for _, tc := range cases {
		for range 200 {
			got := Backoff(tc.attempt, base, ceiling)
			if got < tc.full/2 || got > tc.full {
				t.Fatalf("attempt %d: delay %s outside [%s, %s]", tc.attempt, got, tc.full/2, tc.full)
			}
		}
	}
}

func TestBackoffRejectsNonsenseWithoutPanicking(t *testing.T) {
	for _, tc := range []struct {
		attempt       int
		base, ceiling time.Duration
	}{
		{0, time.Second, time.Minute},
		{-1, time.Second, time.Minute},
		{1, 0, time.Minute},
		{1, time.Second, 0},
	} {
		if got := Backoff(tc.attempt, tc.base, tc.ceiling); got != 0 {
			t.Fatalf("Backoff(%d, %s, %s) = %s, want 0", tc.attempt, tc.base, tc.ceiling, got)
		}
	}
}

func TestEntryAgeReadsTheRedisStreamIDClock(t *testing.T) {
	now := time.UnixMilli(1_700_000_600_000)
	age, ok := EntryAge("1700000000000-3", now)
	if !ok || age != 10*time.Minute {
		t.Fatalf("EntryAge = %s, %v; want 10m, true", age, ok)
	}

	// A creation time slightly ahead of the local clock is fresh, not negative.
	age, ok = EntryAge("1700000600500-0", now)
	if !ok || age != 0 {
		t.Fatalf("future id: EntryAge = %s, %v; want 0, true", age, ok)
	}
}

func TestEntryAgeRefusesUnparseableIDs(t *testing.T) {
	for _, id := range []string{"", "abc", "abc-1", "-1", "0-1", "12345"} {
		if _, ok := EntryAge(id, time.Now()); ok {
			t.Fatalf("EntryAge(%q) parsed; unreadable ids must be treated as fresh", id)
		}
	}
}
