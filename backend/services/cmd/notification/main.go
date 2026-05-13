// Command notification is the Go-side WebSocket fan-out + presence service.
//
// V1 scope (vertical slice):
//   - Subscribes to Redis pub/sub `offer.accepted` from Django.
//   - Holds Flutter client WS sockets; routes to {sender_id, traveler_id}
//     from the payload (CLAUDE.md G1).
//   - Writes `delivered:<event_id>` 60s + updates `core_published_event`
//     so the G6b detection-only outbox sees the receipt.
//   - Refreshes `presence:<user_id>` 15s TTL on every WS ping.
//
// Deferred (see CLAUDE.md §0 / handoff notes):
//   - FCM push fallback (notif:fcm stream consumer) — needs the fcm_token
//     table and a decision on who writes to the stream (Django on_commit
//     vs notif on receipt miss).
//   - Other channels (trip.*, parcel.*, payment.*, match.*) — need a
//     routing scheme that doesn't hardcode payload-field names per channel.
//   - XAUTOCLAIM PEL sweeper — only matters once the stream consumer exists.
//
// Listens on NOTIF_HTTP_ADDR (default :8081). Mounted by Caddy as the
// public /ws prefix; /healthz and /readyz are scraped by the K3s probes.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"shiptrip/internal/notification"
	"shiptrip/pkg/auth"
	"shiptrip/pkg/config"
	"shiptrip/pkg/db"
	"shiptrip/pkg/health"
	"shiptrip/pkg/logger"
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
	httpAddrFallback = ":8081"

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

	rdb, err := redisbus.NewClient(rootCtx, redisbus.Config{
		URL:    redisCfg.URL,
		Logger: log,
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
	dispatcher := notification.NewDispatcher(rdb, pool, hub, log)

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
	mux.HandleFunc("/ws", notification.WSHandler(rootCtx, validator, hub, presence, log))

	srv := &http.Server{
		Addr:              config.HTTPAddr(httpAddrKey, httpAddrFallback),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	dispatcherErr := make(chan error, 1)
	go func() {
		dispatcherErr <- dispatcher.Run(rootCtx)
	}()

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
	log.Info("notification service stopped")
	return fatal
}
