// Command chat is the Go-side WebSocket relay for chat.message.new.
//
// V1 scope (stateless relay — chat_message persistence is Claude A's
// scope until the schema lands):
//   - Subscribes to Redis pub/sub `chat.message.new` from Django.
//   - Holds Flutter client WS sockets keyed by user_id; routes to the
//     single `recipient_id` in the payload (Django picks the other
//     thread member at publish time, same pattern as offer.created).
//   - Writes `delivered:<event_id>` 60s + updates `core_published_event`
//     so the G6b detection-only outbox sees the receipt.
//
// Not implemented in V1 (deferred until schema):
//   - GET /chat/threads / GET /chat/threads/<id>/messages — needs the
//     chat_message sqlc repo (backend/contracts/sql/queries/chat/ is
//     currently empty). Django will own write path.
//   - POST /chat/messages — chat write path goes through Django REST,
//     which then publishes chat.message.new for fan-out. The chat
//     service never writes to chat_message itself.
//   - Presence — owned by the notification service. A user with a chat
//     WS but no notification WS will get a duplicate FCM push for chat
//     events; rare enough for V1 to tolerate.
//
// Listens on CHAT_HTTP_ADDR (default :8081, matches Caddy's
// chat-service:8081 upstream in backend/gateway/Caddyfile). The WS
// handler is mounted at /ws/chat — Caddy preserves the request path,
// it does NOT rewrite. /healthz and /readyz are scraped by K3s probes.
package main

import (
	"context"
	"errors"
	"expvar"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"shiptrip/internal/chat"
	"shiptrip/pkg/auth"
	"shiptrip/pkg/config"
	"shiptrip/pkg/db"
	"shiptrip/pkg/health"
	"shiptrip/pkg/logger"
	"shiptrip/pkg/metrics"
	"shiptrip/pkg/redisbus"
)

const (
	serviceName = "chat"

	// CLAUDE.md §3 reserves 30 Postgres conns for chat (2 pods × 15).
	// One pod in dev → 15. Override at deploy via CHAT_DB_MAX_CONNS.
	dbMaxConnsKey     = "CHAT_DB_MAX_CONNS"
	dbMaxConnsDefault = int32(15)

	httpAddrKey      = "CHAT_HTTP_ADDR"
	httpAddrFallback = ":8081"

	shutdownTimeout = 15 * time.Second
)

func main() {
	if err := run(); err != nil {
		slog.Error("chat service failed", "err", err)
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

	hub := chat.NewHub()
	dispatcher := chat.NewDispatcher(rdb, pool, hub, log, m)

	healthH := health.New(health.Config{Logger: log})
	healthH.Register("postgres", func(ctx context.Context) error { return pool.Ping(ctx) })
	healthH.Register("redis", func(ctx context.Context) error {
		return rdb.SetEX(ctx, "healthz:chat", "1", 5*time.Second)
	})

	mux := http.NewServeMux()
	mux.Handle("/healthz", healthH.Liveness())
	mux.Handle("/readyz", healthH.Readiness())
	// expvar publishes /debug/vars on http.DefaultServeMux at import time.
	// Mount explicitly on our service mux so the scrape target is the
	// admin port, not the default mux that's never served.
	mux.Handle("/debug/vars", expvar.Handler())
	mux.HandleFunc("/ws/chat", chat.WSHandler(rootCtx, validator, hub, log))

	srv := &http.Server{
		Addr:              config.HTTPAddr(httpAddrKey, httpAddrFallback),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		// Mirrors cmd/notification: WS is hijacked at upgrade so the
		// other timeouts would only risk the handshake. IdleTimeout
		// applies to plain HTTP (/healthz, /readyz).
		IdleTimeout: 120 * time.Second,
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
	log.Info("chat service ready")

	var fatal error
	select {
	case <-rootCtx.Done():
		log.Info("shutdown signal received")
	case err := <-serverErr:
		fatal = err
		rootCancel()
	case err := <-dispatcherErr:
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
	select {
	case <-dispatcherErr:
	case <-shutdownCtx.Done():
		log.Warn("dispatcher did not exit before shutdown deadline")
	}
	log.Info("chat service stopped")
	return fatal
}
