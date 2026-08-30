package kyc

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"shiptrip/pkg/redisbus"
)

const rateLimitNamespace = "shiptrip:rate-limit:{kyc-upload}:v1"

// ClientIPSource identifies an explicitly trusted source for the optional IP
// budget. It is deliberately disabled by default: proxy headers are only safe
// identity inputs when the deployment's ingress contract guarantees that
// clients cannot choose them.
type ClientIPSource string

const (
	ClientIPDisabled      ClientIPSource = ""
	ClientIPRemote        ClientIPSource = "remote"
	ClientIPXRealIP       ClientIPSource = "x-real-ip"
	ClientIPXForwardedFor ClientIPSource = "x-forwarded-for"
)

// UploadRateLimitConfig defines the shared KYC upload budgets. The user budget
// is mandatory and authoritative; the IP budget is secondary protection and
// may be disabled with a zero limit when a deployment cannot reliably recover
// client addresses from its trusted proxy.
type UploadRateLimitConfig struct {
	UserLimit  int64
	UserWindow time.Duration
	IPLimit    int64
	IPWindow   time.Duration
}

// UploadRateLimitDecision tells the HTTP boundary whether it may parse and
// store the request body. RetryAfter is populated only for a denied request.
type UploadRateLimitDecision struct {
	Allowed    bool
	RetryAfter time.Duration
}

// UploadRateLimiter is deliberately called after JWT authentication and before
// multipart parsing. That makes the server-derived account identity the primary
// key while oversized and malformed retries still consume abuse budget.
type UploadRateLimiter interface {
	Allow(ctx context.Context, userID int64, clientIP string) (UploadRateLimitDecision, error)
}

type fixedWindowStore interface {
	ConsumeFixedWindow(ctx context.Context, buckets ...redisbus.FixedWindowBucket) (redisbus.FixedWindowDecision, error)
}

// RedisUploadRateLimiter uses Redis fixed-window buckets. The underlying store
// checks every dimension and increments all allowed buckets in one Lua script,
// so separate KYC service instances share the same budget without a
// read-then-write race.
type RedisUploadRateLimiter struct {
	store fixedWindowStore
	cfg   UploadRateLimitConfig
}

func NewRedisUploadRateLimiter(store fixedWindowStore, cfg UploadRateLimitConfig) (*RedisUploadRateLimiter, error) {
	if store == nil {
		return nil, errors.New("kyc rate limiter: shared store is required")
	}
	if cfg.UserLimit <= 0 || cfg.UserWindow <= 0 {
		return nil, errors.New("kyc rate limiter: user limit and window must be positive")
	}
	if cfg.IPLimit < 0 || cfg.IPWindow < 0 {
		return nil, errors.New("kyc rate limiter: ip limit and window cannot be negative")
	}
	if (cfg.IPLimit == 0) != (cfg.IPWindow == 0) {
		return nil, errors.New("kyc rate limiter: ip limit and window must both be zero or both be positive")
	}
	return &RedisUploadRateLimiter{store: store, cfg: cfg}, nil
}

func (l *RedisUploadRateLimiter) Allow(
	ctx context.Context,
	userID int64,
	clientIP string,
) (UploadRateLimitDecision, error) {
	if userID <= 0 {
		return UploadRateLimitDecision{}, errors.New("kyc rate limiter: positive user id is required")
	}

	buckets := []redisbus.FixedWindowBucket{{
		Key:    rateLimitKey("user", strconv.FormatInt(userID, 10), l.cfg.UserWindow),
		Limit:  l.cfg.UserLimit,
		Window: l.cfg.UserWindow,
	}}
	if l.cfg.IPLimit > 0 && clientIP != "" {
		buckets = append(buckets, redisbus.FixedWindowBucket{
			Key:    rateLimitKey("ip", hashIP(clientIP), l.cfg.IPWindow),
			Limit:  l.cfg.IPLimit,
			Window: l.cfg.IPWindow,
		})
	}

	decision, err := l.store.ConsumeFixedWindow(ctx, buckets...)
	if err != nil {
		return UploadRateLimitDecision{}, fmt.Errorf("kyc rate limiter: consume shared budget: %w", err)
	}
	return UploadRateLimitDecision{
		Allowed:    decision.Allowed,
		RetryAfter: decision.RetryAfter,
	}, nil
}

func rateLimitKey(dimension, identity string, window time.Duration) string {
	return fmt.Sprintf(
		"%s:%s:%s:w%d",
		rateLimitNamespace,
		dimension,
		identity,
		window.Milliseconds(),
	)
}

func hashIP(clientIP string) string {
	sum := sha256.Sum256([]byte(clientIP))
	return hex.EncodeToString(sum[:16])
}

// requestClientIP reads only the operator-selected source. Enabling a proxy
// header source is safe only when the trusted ingress strips client-supplied
// values and writes the canonical client address. Invalid or absent addresses
// disable the secondary bucket for that request; the authenticated-user
// budget remains authoritative.
func requestClientIP(r *http.Request, source ClientIPSource) string {
	var raw string
	switch source {
	case ClientIPRemote:
		return canonicalRemoteIP(r.RemoteAddr)
	case ClientIPXRealIP:
		raw = r.Header.Get("X-Real-IP")
	case ClientIPXForwardedFor:
		// A trusted proxy's canonical X-Forwarded-For chain puts the original
		// client first. Do not scan past an invalid first element: doing so
		// would silently switch identities on a malformed header.
		raw = strings.SplitN(r.Header.Get("X-Forwarded-For"), ",", 2)[0]
	case ClientIPDisabled:
		return ""
	default:
		return ""
	}
	if ip := net.ParseIP(strings.TrimSpace(raw)); ip != nil {
		return ip.String()
	}
	return ""
}

func canonicalRemoteIP(remoteAddr string) string {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err == nil {
		if ip := net.ParseIP(host); ip != nil {
			return ip.String()
		}
		return ""
	}
	if ip := net.ParseIP(strings.TrimSpace(remoteAddr)); ip != nil {
		return ip.String()
	}
	return ""
}
