package ifl

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func tradeCfg(site string) Config {
	return Config{SiteInternalURL: site, InternalSecret: strings.Repeat("s", 40)}
}

func TestIsTradeCallback(t *testing.T) {
	cfg := tradeCfg("http://10.98.0.1:8081")
	for raw, want := range map[string]bool{
		"http://10.98.0.1:8081/internal/chat/trade/action":         true,
		"http://10.98.0.1:8081/internal/chat/trade/dialog":         true,
		"http://10.98.0.1:8081/internal/chat/trade/command":        false, // only the fork calls this
		"http://10.98.0.1:8081/internal/chat/users/1/suspension":   false,
		"http://10.98.0.1:8081/internal/chat/trade/action?x=1":     false,
		"http://10.98.0.1:8081/internal/chat/trade/action#x":       false,
		"http://10.98.0.1:8081/internal/chat/trade/action/../../x": false,
		"http://10.98.0.1:8081/internal/chat/trade%2Faction":       false,
		"http://u:p@10.98.0.1:8081/internal/chat/trade/action":     false,
		"https://10.98.0.1:8081/internal/chat/trade/action":        false,
		"http://10.98.0.1:8082/internal/chat/trade/action":         false,
		"http://10.98.0.1/internal/chat/trade/action":              false,
		"http://evil.example/internal/chat/trade/action":           false,
	} {
		u, err := url.Parse(raw)
		require.NoError(t, err)
		require.Equal(t, want, cfg.IsTradeCallback(u), raw)
	}
	u, _ := url.Parse("http://10.98.0.1:8081/internal/chat/trade/action")
	require.False(t, Config{SiteInternalURL: "http://10.98.0.1:8081"}.IsTradeCallback(u), "no secret, no signing")
	require.False(t, tradeCfg("").IsTradeCallback(u))
	require.False(t, tradeCfg("http://10.98.0.1:8081").IsTradeCallback(nil))
}

func TestTradeCommand(t *testing.T) {
	var got *http.Request
	var body map[string]string
	site := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r
		require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
		_, _ = w.Write([]byte(`{"text":"pick a team"}`))
	}))
	defer site.Close()

	res, err := NewSiteClient(tradeCfg(site.URL)).TradeCommand(context.Background(), "16", "trig", "ch1", "MIA")
	require.NoError(t, err)
	require.Equal(t, "pick a team", res.Text)
	require.Equal(t, TradeCommandPath, got.URL.Path)
	require.Equal(t, strings.Repeat("s", 40), got.Header.Get(SecretHeader))
	require.Equal(t, "16", got.Header.Get(SiteUserHeader))
	require.Equal(t, map[string]string{"trigger_id": "trig", "channel_id": "ch1", "text": "MIA"}, body)
}

func TestTradeCommandRefusals(t *testing.T) {
	site := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer site.Close()
	_, err := NewSiteClient(tradeCfg(site.URL)).TradeCommand(context.Background(), "16", "t", "c", "")
	require.ErrorContains(t, err, "refused")
	_, err = NewSiteClient(tradeCfg(site.URL)).TradeCommand(context.Background(), "16 OR 1", "t", "c", "")
	require.ErrorContains(t, err, "invalid site user id")
	_, err = NewSiteClient(Config{}).TradeCommand(context.Background(), "16", "t", "c", "")
	require.ErrorContains(t, err, "not configured")
}
