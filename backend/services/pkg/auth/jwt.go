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

	// accessTokenType is the value SimpleJWT puts in the `typ` claim
	// for access tokens. Refresh tokens carry `typ=refresh` and must
	// never authenticate a request.
	accessTokenType = "access"
)

type Validator struct {
	secret []byte
	logger *slog.Logger
}

// Claims mirrors the SimpleJWT payload Django emits.
// `UserID` is the integer PK (Django's BigAutoField) — never a string.
// `Type` distinguishes access (`access`) from refresh (`refresh`) tokens.
type Claims struct {
	UserID int64  `json:"user_id"`
	Role   string `json:"role"`
	Type   string `json:"typ"`
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
	if claims.UserID == 0 {
		return nil, errors.New("missing or zero user_id claim")
	}
	if claims.Type != accessTokenType {
		// Refresh tokens carry the same signature as access tokens but
		// must never authenticate API or WS requests.
		return nil, fmt.Errorf("token type %q is not an access token", claims.Type)
	}

	if claims.IssuedAt != nil {
		drift := time.Until(claims.IssuedAt.Time)
		if drift > driftWarnThreshold {
			v.logger.Warn("jwt iat ahead of now (clock drift)",
				"drift_ms", drift.Milliseconds(),
				"user_id", claims.UserID,
			)
		}
	}

	return claims, nil
}
