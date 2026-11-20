package ifl

import (
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const testSecret = "0123456789abcdef0123456789abcdef0123"

func sign(t *testing.T, method jwt.SigningMethod, key any, claims jwt.MapClaims) string {
	t.Helper()
	s, err := jwt.NewWithClaims(method, claims).SignedString(key)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func good(now time.Time) jwt.MapClaims {
	return jwt.MapClaims{
		"aud": "ifl-chat", "iss": "iflgm.com", "sub": "42",
		"iat": now.Unix(), "exp": now.Add(120 * time.Second).Unix(),
		"jti":      "0123456789abcdef0123456789abcdef",
		"username": "gm1", "email": "gm1@example.test", "name": "Josh H",
	}
}

func TestVerifyPanelToken(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	c, err := VerifyPanelToken(sign(t, jwt.SigningMethodHS256, []byte(testSecret), good(now)), testSecret, now)
	if err != nil {
		t.Fatal(err)
	}
	if c.SiteID != 42 || c.Username != "gm1" || c.Email != "gm1@example.test" || c.Name != "Josh H" || c.JTI != "0123456789abcdef0123456789abcdef" {
		t.Fatalf("claims: %+v", c)
	}
}

func TestVerifyPanelTokenRejects(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	cases := map[string]func(jwt.MapClaims){
		"wrong aud":       func(m jwt.MapClaims) { m["aud"] = "other" },
		"wrong iss":       func(m jwt.MapClaims) { m["iss"] = "evil" },
		"expired":         func(m jwt.MapClaims) { m["exp"] = now.Add(-31 * time.Second).Unix() },
		"too long":        func(m jwt.MapClaims) { m["exp"] = now.Add(10 * time.Minute).Unix() },
		"future iat":      func(m jwt.MapClaims) { m["iat"] = now.Add(time.Minute).Unix() },
		"non-numeric sub": func(m jwt.MapClaims) { m["sub"] = "abc" },
		"zero sub":        func(m jwt.MapClaims) { m["sub"] = "0" },
		"bad jti":         func(m jwt.MapClaims) { m["jti"] = "short" },
		"no email":        func(m jwt.MapClaims) { delete(m, "email") },
		"no username":     func(m jwt.MapClaims) { delete(m, "username") },
		"no name":         func(m jwt.MapClaims) { delete(m, "name") },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			m := good(now)
			mutate(m)
			if _, err := VerifyPanelToken(sign(t, jwt.SigningMethodHS256, []byte(testSecret), m), testSecret, now); err == nil {
				t.Fatal("accepted")
			}
		})
	}
	t.Run("wrong secret", func(t *testing.T) {
		tok := sign(t, jwt.SigningMethodHS256, []byte("another-secret-another-secret-0000"), good(now))
		if _, err := VerifyPanelToken(tok, testSecret, now); err == nil {
			t.Fatal("accepted")
		}
	})
	t.Run("alg none", func(t *testing.T) {
		tok := sign(t, jwt.SigningMethodNone, jwt.UnsafeAllowNoneSignatureType, good(now))
		if _, err := VerifyPanelToken(tok, testSecret, now); err == nil {
			t.Fatal("accepted")
		}
	})
	t.Run("HS512", func(t *testing.T) {
		tok := sign(t, jwt.SigningMethodHS512, []byte(testSecret), good(now))
		if _, err := VerifyPanelToken(tok, testSecret, now); err == nil {
			t.Fatal("accepted")
		}
	})
}
