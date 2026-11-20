package ifl

import (
	"errors"
	"regexp"
	"strconv"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// PanelClaims is the site's identity assertion for the chat panel
// (league chat plan 3A, /api/league-chat/session-token).
type PanelClaims struct {
	SiteID   int64
	Username string
	Email    string
	Name     string
	JTI      string
	Expires  time.Time
}

const (
	panelAudience = "ifl-chat"
	panelIssuer   = "iflgm.com"
	panelLeeway   = 30 * time.Second
	panelMaxLife  = 150 * time.Second
)

var jtiPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)

type panelJWT struct {
	Username string `json:"username"`
	Email    string `json:"email"`
	Name     string `json:"name"`
	jwt.RegisteredClaims
}

func VerifyPanelToken(token, secret string, now time.Time) (*PanelClaims, error) {
	if len(secret) < minSecretLength {
		return nil, errors.New("panel sessions are not configured")
	}
	var c panelJWT
	parsed, err := jwt.ParseWithClaims(token, &c, func(*jwt.Token) (any, error) { return []byte(secret), nil },
		jwt.WithValidMethods([]string{"HS256"}),
		jwt.WithAudience(panelAudience),
		jwt.WithIssuer(panelIssuer),
		jwt.WithExpirationRequired(),
		jwt.WithIssuedAt(),
		jwt.WithLeeway(panelLeeway),
		jwt.WithTimeFunc(func() time.Time { return now }),
	)
	if err != nil || !parsed.Valid {
		return nil, errors.New("invalid panel token")
	}
	if c.IssuedAt == nil || c.ExpiresAt == nil || c.ExpiresAt.Sub(c.IssuedAt.Time) > panelMaxLife {
		return nil, errors.New("invalid panel token lifetime")
	}
	id, err := strconv.ParseInt(c.Subject, 10, 64)
	if err != nil || id <= 0 {
		return nil, errors.New("invalid panel token subject")
	}
	if !jtiPattern.MatchString(c.ID) || c.Username == "" || c.Email == "" {
		return nil, errors.New("incomplete panel token")
	}
	return &PanelClaims{SiteID: id, Username: c.Username, Email: c.Email, Name: c.Name,
		JTI: c.ID, Expires: c.ExpiresAt.Time}, nil
}
