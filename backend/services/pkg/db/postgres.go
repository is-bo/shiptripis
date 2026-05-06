package db

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Config struct {
	URL             string
	MaxConns        int32
	MinConns        int32
	MaxConnLifetime time.Duration
	MaxConnIdleTime time.Duration
	Logger          *slog.Logger
}

func NewPool(ctx context.Context, cfg Config) (*pgxpool.Pool, error) {
	if cfg.URL == "" {
		return nil, errors.New("database url is empty")
	}
	if cfg.MaxConns <= 0 {
		return nil, errors.New("max conns must be > 0")
	}

	log := cfg.Logger
	if log == nil {
		log = slog.Default()
	}

	poolCfg, err := pgxpool.ParseConfig(cfg.URL)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}

	poolCfg.MaxConns = cfg.MaxConns
	poolCfg.MinConns = orDefault(cfg.MinConns, int32(2))
	poolCfg.MaxConnLifetime = orDefault(cfg.MaxConnLifetime, time.Hour)
	poolCfg.MaxConnIdleTime = orDefault(cfg.MaxConnIdleTime, 30*time.Minute)

	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}

	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}

	log.Info("postgres pool ready",
		"max_conns", poolCfg.MaxConns,
		"min_conns", poolCfg.MinConns,
	)

	return pool, nil
}

func orDefault[T comparable](v, d T) T {
	var zero T
	if v == zero {
		return d
	}
	return v
}
