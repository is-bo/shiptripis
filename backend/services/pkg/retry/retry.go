// Package retry holds the two retry primitives the Redis stream workers
// share, so the FCM and email consumers bound their retries the same way.
//
// Both consumers retry by leaving an entry in the PEL for the XAUTOCLAIM
// sweeper, which on its own retries forever. Two bounds close that:
//
//  1. Backoff spaces out retries a worker schedules itself (the FCM
//     partial-token retry), with jitter so a burst of failures does not
//     retry in lockstep.
//  2. EntryAge reads the creation time Redis encodes in every stream ID, so a
//     worker can stop retrying an entry once it is older than its useful
//     window without any extra Redis round trip or attempt counter.
package retry

import (
	"math/rand/v2"
	"strconv"
	"strings"
	"time"
)

// Backoff returns the delay before retry number attempt (1-based): base
// doubled per attempt, capped at ceiling, then "equal jitter" — a uniform
// value in [d/2, d]. The floor keeps a retry from firing immediately; the
// jitter keeps simultaneous failures from retrying together. Non-positive
// inputs return zero rather than panicking.
func Backoff(attempt int, base, ceiling time.Duration) time.Duration {
	if attempt < 1 || base <= 0 || ceiling <= 0 {
		return 0
	}
	d := base
	for i := 1; i < attempt && d < ceiling; i++ {
		d *= 2
	}
	if d > ceiling {
		d = ceiling
	}
	half := d / 2
	return half + time.Duration(rand.Int64N(int64(d-half)+1))
}

// EntryAge returns how long ago Redis created the stream entry with the
// given ID ("<unix-ms>-<seq>"). ok is false for an ID it cannot parse, and
// callers must then treat the entry as fresh: an unreadable ID is never a
// reason to drop work.
func EntryAge(id string, now time.Time) (age time.Duration, ok bool) {
	ms, _, found := strings.Cut(id, "-")
	if !found {
		return 0, false
	}
	created, err := strconv.ParseInt(ms, 10, 64)
	if err != nil || created <= 0 {
		return 0, false
	}
	age = now.Sub(time.UnixMilli(created))
	if age < 0 {
		// Redis and this process share a host clock in the combined
		// container; a small skew against external Redis is not an age.
		age = 0
	}
	return age, true
}
