// Command notification is the Go-side WebSocket fan-out + presence service.
//
// Scope:
//   - Subscribes to Django notification pub/sub channels (chat has its own
//     relay; see notification.subscribeChannels and apps/core/channels.py).
//   - Holds Flutter client WS sockets; routes each envelope generically by
//     its targets:[uid,...] field to every target's local sockets (CLAUDE.md G1).
//   - Writes `delivered:<event_id>:<user_id>` for 60s and updates `core_published_event`
//     so the G6b detection-only outbox sees the receipt.
//   - Refreshes `presence:<user_id>` 15s TTL while the socket is live.
//
// FCM push fallback is implemented and gated by FCM_ENABLED (default false).
// With valid project/credential configuration it uses Firebase Admin behind
// an XREADGROUP/XAUTOCLAIM worker. The consumer waits two seconds, checks the
// recipient-specific WebSocket receipt, then sends or suppresses and XACKs.
//
// Listens on NOTIF_HTTP_ADDR (default :8082, matches Caddy's
// notification-service:8082 upstream in backend/gateway/Caddyfile). The
// WS handler is mounted at /ws/notifications because Caddy's
// reverse_proxy preserves the request path — it does NOT rewrite
// /ws/notifications to /ws. If you ever change the public path, change
// both this mount and the Caddyfile in the same commit. /healthz and
// /readyz are scraped by the K3s probes.
package main

import (
	"context"
	"errors"
	"expvar"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"shiptrip/internal/notification"
	"shiptrip/pkg/auth"
	"shiptrip/pkg/config"
	"shiptrip/pkg/db"
	"shiptrip/pkg/health"
	"shiptrip/pkg/logger"
	"shiptrip/pkg/metrics"
	"shiptrip/pkg/redisbus"
)

const (
	serviceName = "notification"

	// Per-service Postgres connection budget. CLAUDE.md §3 reserves 10
	// conns to notif (1 pod × 10). Override at deploy time via
	// NOTIF_DB_MAX_CONNS if pod count changes.
	dbMaxConnsKey     = "NOTIF_DB_MAX_CONNS"
	dbMaxConnsDefault = int32(10)

	httpAddrKey      = "NOTIF_HTTP_ADDR"
	httpAddrFallback = ":8082"

	shutdownTimeout = 15 * time.Second
)

func main() {
	if err := run(); err != nil {
		// Logger may not be up yet; bare slog is fine for crash exit.
		slog.Error("notification service failed", "err", err)
		os.Exit(1)
	}
}

func run() error {
	log := logger.New(logger.Config(config.LoadLogger(serviceName)))

	pgCfg, err := config.LoadPostgres(dbMaxConnsKey, dbMaxConnsDefault)
	if err != nil {
		return err
	}
	redisCfg, err := config.LoadRedis()
	if err != nil {
		return err
	}
	jwtCfg, err := config.LoadJWT()
	if err != nil {
		return err
	}
	fcmCfg, err := config.LoadFCM()
	if err != nil {
		return err
	}

	signalCtx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	// rootCtx is the service-lifetime ctx. Cancelling it tears down every
	// long-running thing wired below (dispatcher, WS handlers, presence
	// refreshers). We derive it from the signal ctx so SIGTERM cancels
	// rootCtx; we also cancel it explicitly when any leg exits early so
	// the other legs don't keep running on a dead service.
	rootCtx, rootCancel := context.WithCancel(signalCtx)
	defer rootCancel()

	pool, err := db.NewPool(rootCtx, db.Config{
		URL:      pgCfg.URL,
		MaxConns: pgCfg.MaxConns,
		Logger:   log,
	})
	if err != nil {
		return err
	}
	defer pool.Close()

	m := metrics.Register(serviceName)

	rdb, err := redisbus.NewClient(rootCtx, redisbus.Config{
		URL:     redisCfg.URL,
		Logger:  log,
		Metrics: m,
	})
	if err != nil {
		return err
	}
	defer func() { _ = rdb.Close() }()

	validator, err := auth.NewValidator(jwtCfg.Secret, log)
	if err != nil {
		return err
	}

	hub := notification.NewHub()
	presence := notification.NewPresence(rdb, log)
	dispatcher := notification.NewDispatcher(rdb, pool, hub, log, m)

	// connWG tracks in-flight WS handler goroutines. Hijacked WS conns are
	// invisible to srv.Shutdown, so we drain them explicitly below before the
	// deferred rdb.Close()/pool.Close() — otherwise a handler's presence.Drop
	// could race a closed Redis client on shutdown.
	var connWG sync.WaitGroup

	healthH := health.New(health.Config{Logger: log})
	healthH.Register("postgres", func(ctx context.Context) error { return pool.Ping(ctx) })
	healthH.Register("redis", func(ctx context.Context) error {
		// Use a small probe — SetEX with self-expiring sentinel touches
		// the same code path as presence/delivered writes.
		return rdb.SetEX(ctx, "healthz:notification", "1", 5*time.Second)
	})

	mux := http.NewServeMux()
	mux.Handle("/healthz", healthH.Liveness())
	mux.Handle("/readyz", healthH.Readiness())
	// expvar publishes /debug/vars on http.DefaultServeMux at import time.
	// Mount it explicitly on our service mux so the metric scrape target is
	// the admin port, not the default mux that's never served.
	mux.Handle("/debug/vars", expvar.Handler())
	mux.HandleFunc("/ws/notifications", notification.WSHandler(rootCtx, validator, hub, presence, log, m, &connWG))

	srv := &http.Server{
		Addr:              config.HTTPAddr(httpAddrKey, httpAddrFallback),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		// IdleTimeout governs HTTP/1.1 keep-alive on /healthz, /readyz.
		// WS connections are hijacked at Upgrade and aren't subject to
		// the server's Write/Read timeouts after that — adding them
		// here would only risk breaking the upgrade itself.
		IdleTimeout: 120 * time.Second,
	}

	dispatcherErr := make(chan error, 1)
	go func() {
		dispatcherErr <- dispatcher.Run(rootCtx)
	}()

	// FCM consumer + XAUTOCLAIM sweeper. Two goroutines because the
	// blocking XReadGroup would otherwise stall the periodic sweep.
	// Both share the same channel so any fatal exit cancels rootCtx.
	// fcmAlive tracks how many of {Run, Sweep} are still alive so the
	// drain loop below waits for exactly the right count — if the outer
	// select consumed one fcmErr, only one remains to drain.
	fcmErr := make(chan error, 2)
	fcmAlive := 0
	if fcmCfg.Enabled {
		// Build the real Firebase sender from the service-account JSON.
		// Fail loud at boot on bad/unreadable credentials (CLAUDE.md §9)
		// rather than discovering it on the first push. LoadFCM already
		// guarantees ProjectID + CredentialsPath are set when Enabled.
		sender, err := notification.NewFirebaseSender(rootCtx, fcmCfg.ProjectID, fcmCfg.CredentialsPath, log)
		if err != nil {
			return err
		}
		fcm := notification.NewConsumer(rdb, notification.ConsumerConfig{
			Stream:         fcmCfg.Stream,
			ConsumerGroup:  fcmCfg.ConsumerGroup,
			ConsumerName:   fcmCfg.ConsumerName,
			FeedbackStream: fcmCfg.ResultsStream,
			Sender:         sender,
		}, log)
		go func() { fcmErr <- fcm.Run(rootCtx) }()
		go func() { fcmErr <- fcm.Sweep(rootCtx) }()
		fcmAlive = 2
		log.Info("fcm consumer enabled", "stream", fcmCfg.Stream)
	} else {
		log.Info("fcm consumer disabled (FCM_ENABLED=false)")
	}

	serverErr := make(chan error, 1)
	go func() {
		log.Info("http listening", "addr", srv.Addr)
		err := srv.ListenAndServe()
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		serverErr <- err
	}()

	healthH.MarkReady()
	log.Info("notification service ready")

	var fatal error
	select {
	case <-rootCtx.Done():
		log.Info("shutdown signal received")
	case err := <-serverErr:
		// HTTP server stopped on its own. Tear the rest down before exit.
		fatal = err
		rootCancel()
	case err := <-dispatcherErr:
		// Dispatcher exited on its own. A nil return means it raced
		// rootCtx.Done — graceful. Anything else is fatal, and we cancel
		// rootCtx so WS handlers and the HTTP server unwind too.
		if err != nil {
			fatal = errors.Join(errors.New("dispatcher exited"), err)
		}
		rootCancel()
	case err := <-fcmErr:
		// One of {Run, Sweep} exited early. nil = graceful (ctx cancelled
		// by another leg already). Non-nil = fatal; tear down everything.
		// Either way one of the two FCM goroutines is gone — the drain
		// loop below only needs to wait for the survivor.
		fcmAlive--
		if err != nil {
			fatal = errors.Join(errors.New("fcm consumer exited"), err)
		}
		rootCancel()
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Warn("http shutdown error", "err", err)
	}
	// Drain the dispatcher if it hasn't already exited.
	select {
	case <-dispatcherErr:
	case <-shutdownCtx.Done():
		log.Warn("dispatcher did not exit before shutdown deadline")
	}
	// Drain remaining FCM goroutines. fcmAlive was decremented if the
	// outer select consumed one; without that bookkeeping we'd hang on a
	// phantom receive every clean shutdown that fired on fcmErr.
	for range fcmAlive {
		select {
		case <-fcmErr:
		case <-shutdownCtx.Done():
			log.Warn("fcm goroutine did not exit before shutdown deadline")
		}
	}
	// Wait for in-flight WS handlers (hijacked conns srv.Shutdown can't see)
	// to finish their presence.Drop before the deferred rdb/pool close fire.
	// rootCtx is already cancelled here, so each conn.Read has unblocked.
	// Bounded by shutdownCtx so a wedged handler can't hang the process.
	if !waitWithCtx(shutdownCtx, &connWG) {
		log.Warn("ws handlers did not drain before shutdown deadline")
	}
	log.Info("notification service stopped")
	return fatal
}

// waitWithCtx blocks until wg is done or ctx expires. Returns true if the
// WaitGroup drained, false if the context deadline hit first.
func waitWithCtx(ctx context.Context, wg *sync.WaitGroup) bool {
	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()
	select {
	case <-done:
		return true
	case <-ctx.Done():
		return false
	}
}
