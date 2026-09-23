package redisbus

import (
	"errors"
	"fmt"
	"testing"
	"time"
)

func TestGroupStartIDLooksBackAFixedWindow(t *testing.T) {
	now := time.UnixMilli(1_800_000_000_000)
	want := fmt.Sprintf("%d-0", now.Add(-GroupCreateLookback).UnixMilli())
	if got := GroupStartID(now); got != want {
		t.Fatalf("GroupStartID = %q, want %q", got, want)
	}
	// Neither "$" (skips entries appended before the group existed) nor "0"
	// (replays the whole capped history) is acceptable for a durable stream.
	if got := GroupStartID(now); got == "$" || got == "0" || got == "0-0" {
		t.Fatalf("GroupStartID = %q, want a bounded lookback ID", got)
	}
}

func TestGroupStartIDNeverGoesNegative(t *testing.T) {
	if got := GroupStartID(time.UnixMilli(1_000)); got != "0-0" {
		t.Fatalf("GroupStartID near the epoch = %q, want 0-0", got)
	}
}

func TestIsNoGroup(t *testing.T) {
	cases := []struct {
		err  error
		want bool
	}{
		{errors.New("NOGROUP No such key 'email:send' or consumer group 'g' in XREADGROUP with GROUP option"), true},
		{errors.New("BUSYGROUP Consumer Group name already exists"), false},
		{errors.New("dial tcp: connection refused"), false},
		{nil, false},
	}
	for _, tc := range cases {
		if got := IsNoGroup(tc.err); got != tc.want {
			t.Errorf("IsNoGroup(%v) = %v, want %v", tc.err, got, tc.want)
		}
	}
}
