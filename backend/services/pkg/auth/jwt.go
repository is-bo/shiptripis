package auth

import (
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const (
	clockSkewLeeway    = 30 * time.Second
	driftWarnThreshold = 5 * time.Second
)

type Validator struct {
	secret []byte
	logger *slog.Logger
}

type Claims struct {
	Role string `json:"role"`
	jwt.RegisteredClaims
}

func NewValidator(secret string, logger *slog.Logger) (*Validator, error) {
	if secret == "" {
		return nil, errors.New("jwt secret is empty")
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &Validator{secret: []byte(secret), logger: logger}, nil
}

func (v *Validator) Validate(tokenString string) (*Claims, error) {
	parser := jwt.NewParser(
		jwt.WithLeeway(clockSkewLeeway),
		jwt.WithValidMethods([]string{"HS256"}),
	)

	token, err := parser.ParseWithClaims(tokenString, &Claims{}, func(t *jwt.Token) (any, error) {
		return v.secret, nil
	})
	if err != nil {
		return nil, fmt.Errorf("token validation failed: %w", err)
	}

	claims, ok := token.Claims.(*Claims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid token payload")
	}
	if claims.Subject == "" {
		return nil, errors.New("missing sub claim")
	}

	if claims.IssuedAt != nil {
		drift := time.Until(claims.IssuedAt.Time)
		if drift > driftWarnThreshold {
			v.logger.Warn("jwt iat ahead of now (clock drift)",
				"drift_ms", drift.Milliseconds(),
				"sub", claims.Subject,
			)
		}
	}

	return claims, nil
}
