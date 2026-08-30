// Command email is the Go-side transactional-email service.
//
// Scope:
//   - Consumes the durable `email:send` Redis Stream that Django XADDs rendered
//     messages onto (signup verification + password-reset OTP).
//   - Sends each over SMTP via internal/email. Django owns the copy/templates;
//     this service is a pure transport.
//
// It is intentionally minimal: no JWT or WebSocket. It uses a small PostgreSQL
// pool only for durable SMTP delivery receipts; Django still owns OTP
// generation, verification and the transactional outbox. The service exposes
// a Redis stream consumer plus an HTTP admin surface (/healthz, /readyz,
// /debug/vars).
//
// Gated by EMAIL_ENABLED (default false). Flipping EMAIL_ENABLED=true and
// supplying EMAIL_SMTP_* activates the consumer + sweeper.
// While disabled the process still boots and serves health, so it can sit in
// compose harmlessly.
//
// Listens on EMAIL_HTTP_ADDR (default :8085). There is no public gateway route —
// the service exposes only internal ops endpoints (a pure stream consumer, like
// the FCM path). /healthz and /readyz are scraped by the K3s probes.
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

	"shiptrip/internal/email"
	"shiptrip/pkg/config"
	"shiptrip/pkg/db"
	"shiptrip/pkg/health"
	"shiptrip/pkg/logger"
	"shiptrip/pkg/metrics"
	"shiptrip/pkg/redisbus"
)

const (
	serviceName             = "email"
	dbMaxConnsKey           = "EMAIL_DB_MAX_CONNS"
	dbMaxConnsDefault int32 = 5

	httpAddrKey      = "EMAIL_HTTP_ADDR"
	httpAddrFallback = ":8085"

	shutdownTimeout = 15 * time.Second
)

func main() {
	if err := run(); err != nil {
		slog.Error("email service failed", "err", err)
		os.Exit(1)
	}
}

func run() error {
	log := logger.New(logger.Config(config.LoadLogger(serviceName)))

	redisCfg, err := config.LoadRedis()
	if err != nil {
		return err
	}
	pgCfg, err := config.LoadPostgres(dbMaxConnsKey, dbMaxConnsDefault)
	if err != nil {
		return err
	}
	emailCfg, err := config.LoadEmail()
	if err != nil {
		return err
	}

	signalCtx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	// rootCtx is the service-lifetime ctx. Cancelling it tears down the
	// consumer + sweeper. Derived from signalCtx so SIGTERM cancels it; also
	// cancelled explicitly when any leg exits early so the others don't keep
	// running on a dead service.
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

	healthH := health.New(health.Config{Logger: log})
	healthH.Register("postgres", func(ctx context.Context) error { return pool.Ping(ctx) })
	healthH.Register("redis", func(ctx context.Context) error {
		// Small probe touching the same SetEX code path the consumer uses.
		return rdb.SetEX(ctx, "healthz:email", "1", 5*time.Second)
	})

	mux := http.NewServeMux()
	mux.Handle("/healthz", healthH.Liveness())
	mux.Handle("/readyz", healthH.Readiness())
	// expvar publishes /debug/vars on http.DefaultServeMux at import time;
	// mount it on our service mux so the scrape target is the admin port.
	mux.Handle("/debug/vars", expvar.Handler())

	srv := &http.Server{
		Addr:              config.HTTPAddr(httpAddrKey, httpAddrFallback),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	// Email consumer + XAUTOCLAIM sweeper. Two goroutines because the blocking
	// XReadGroup would otherwise stall the periodic sweep. Both share one
	// channel so any fatal exit cancels rootCtx. emailAlive tracks how many of
	// {Run, Sweep} are still alive so the drain loop waits for exactly the
	// right count — if the outer select consumed one emailErr, only one remains.
	emailErr := make(chan error, 2)
	emailAlive := 0
	if emailCfg.Enabled {
		// Build the real SMTP sender. Fail loud at boot on bad config
		// (CLAUDE.md §9). LoadEmail already guarantees host/port/from are set
		// when Enabled.
		sender, err := email.NewSMTPSender(email.SMTPConfig{
			Host:     emailCfg.SMTPHost,
			Port:     emailCfg.SMTPPort,
			Username: emailCfg.SMTPUsername,
			Password: emailCfg.SMTPPassword,
			FromAddr: emailCfg.FromAddr,
			FromName: emailCfg.FromName,
			UseTLS:   emailCfg.UseTLS,
		}, log)
		if err != nil {
			return err
		}
		receipts, err := email.NewPostgresReceiptStore(pool)
		if err != nil {
			return err
		}
		consumer := email.NewConsumer(rdb, email.ConsumerConfig{
			Stream:        emailCfg.Stream,
			ConsumerGroup: emailCfg.ConsumerGroup,
			ConsumerName:  emailCfg.ConsumerName,
			Sender:        sender,
			Receipts:      receipts,
		}, log)
		go func() { emailErr <- consumer.Run(rootCtx) }()
		go func() { emailErr <- consumer.Sweep(rootCtx) }()
		emailAlive = 2
		log.Info("email consumer enabled", "stream", emailCfg.Stream)
	} else {
		log.Info("email consumer disabled (EMAIL_ENABLED=false)")
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
	log.Info("email service ready")

	var fatal error
	select {
	case <-rootCtx.Done():
		log.Info("shutdown signal received")
	case err := <-serverErr:
		fatal = err
		rootCancel()
	case err := <-emailErr:
		// One of {Run, Sweep} exited early. nil = graceful (ctx cancelled by
		// another leg). Non-nil = fatal; tear down everything. Either way one
		// goroutine is gone, so the drain loop only waits for the survivor.
		emailAlive--
		if err != nil {
			fatal = errors.Join(errors.New("email consumer exited"), err)
		}
		rootCancel()
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Warn("http shutdown error", "err", err)
	}
	// Drain remaining email goroutines. emailAlive was decremented if the outer
	// select consumed one; without that bookkeeping we'd hang on a phantom
	// receive every clean shutdown that fired on emailErr.
	for range emailAlive {
		select {
		case <-emailErr:
		case <-shutdownCtx.Done():
			log.Warn("email goroutine did not exit before shutdown deadline")
		}
	}
	log.Info("email service stopped")
	return fatal
}
