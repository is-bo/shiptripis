// Command kyc is the Go-side KYC service (ARCHITECTURE.md §6).
//
// V1 scope:
//   - POST /kyc/submit — multipart upload, streams images to S3/MinIO
//     under `kyc-docs/<user_id>/<uuid>.<ext>`, then calls Django's
//     KYCSubmissionService.RecordSubmission via gRPC for the durable row.
//   - /healthz, /readyz for K3s probes.
//
// Deferred until contracts/grpc/kyc.proto codegen lands and Django ships
// apps/kyc/grpc_server.py + the idempotency_key migration:
//   - The gRPC client itself. We wire kyc.NoopRecorder for now, which
//     fails loudly so a half-built production deploy is impossible to
//     miss.
//   - GET /kyc/me (status lookup) — needs sqlc-generated repo.
//
// Listens on KYC_HTTP_ADDR (default :8082); Caddy routes /api/v1/kyc/*
// here (ARCHITECTURE.md §3).
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

	"shiptrip/internal/kyc"
	"shiptrip/pkg/auth"
	"shiptrip/pkg/config"
	"shiptrip/pkg/db"
	"shiptrip/pkg/health"
	"shiptrip/pkg/logger"
	"shiptrip/pkg/storage"
)

const (
	serviceName = "kyc"

	// CLAUDE.md §3 reserves 5 Postgres conns for the Go kyc-service.
	// Override at deploy time via KYC_DB_MAX_CONNS if the pod count or
	// the global budget changes.
	dbMaxConnsKey     = "KYC_DB_MAX_CONNS"
	dbMaxConnsDefault = int32(5)

	httpAddrKey      = "KYC_HTTP_ADDR"
	httpAddrFallback = ":8082"

	// Bucket holding KYC document images. Lives in its own bucket so
	// access policies can be tightened independently of profile media.
	bucketEnvKey      = "KYC_S3_BUCKET"
	bucketEnvFallback = "kyc-docs"

	shutdownTimeout = 15 * time.Second
)

func main() {
	if err := run(); err != nil {
		slog.Error("kyc service failed", "err", err)
		os.Exit(1)
	}
}

func run() error {
	log := logger.New(logger.Config(config.LoadLogger(serviceName)))

	pgCfg, err := config.LoadPostgres(dbMaxConnsKey, dbMaxConnsDefault)
	if err != nil {
		return err
	}
	jwtCfg, err := config.LoadJWT()
	if err != nil {
		return err
	}
	s3Cfg, err := config.LoadS3()
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

	store, err := storage.New(rootCtx, storage.Config{
		Endpoint:     s3Cfg.Endpoint,
		Region:       s3Cfg.Region,
		AccessKey:    s3Cfg.AccessKey,
		SecretKey:    s3Cfg.SecretKey,
		UsePathStyle: s3Cfg.UsePathStyle,
		Logger:       log,
	})
	if err != nil {
		return err
	}

	validator, err := auth.NewValidator(jwtCfg.Secret, log)
	if err != nil {
		return err
	}

	bucket := config.String(bucketEnvKey, bucketEnvFallback)

	handler := &kyc.Handler{
		Validator: validator,
		Storage:   store,
		Bucket:    bucket,
		Recorder:  kyc.NoopRecorder{}, // TODO(claude-b): swap for grpc client when codegen lands
		Log:       log,
	}

	healthH := health.New(health.Config{Logger: log})
	healthH.Register("postgres", func(ctx context.Context) error { return pool.Ping(ctx) })
	healthH.Register("s3", func(ctx context.Context) error { return store.Ping(ctx, bucket) })

	mux := http.NewServeMux()
	mux.Handle("GET /healthz", healthH.Liveness())
	mux.Handle("GET /readyz", healthH.Readiness())
	handler.Mount(mux)

	srv := &http.Server{
		Addr:              config.HTTPAddr(httpAddrKey, httpAddrFallback),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
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
	log.Info("kyc service ready", "bucket", bucket)

	var fatal error
	select {
	case <-rootCtx.Done():
		log.Info("shutdown signal received")
	case err := <-serverErr:
		fatal = err
		rootCancel()
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Warn("http shutdown error", "err", err)
	}
	log.Info("kyc service stopped")
	return fatal
}
