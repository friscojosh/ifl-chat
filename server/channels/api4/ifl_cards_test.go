// IFL: league chat fork (app cards). The score and news card routes.
package api4

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

const iflCardTestSecret = "internal-secret-internal-secret-cards"

const iflScoreBody = `{"week":{"id":3,"week_number":12,"is_playoff":false},"matchup":{"id":4512,"status":"live",` +
	`"home_score":null,"away_score":null,"home_live_score":101.4,"away_live_score":88.2,` +
	`"home_record":"7-4","away_record":"6-5","home_left":2,"away_left":0,` +
	`"home_team":{"id":16,"name":"Los Angeles Chargers","abbreviation":"LAC","logo_url":null,"badge_abbr":"LAC"},` +
	`"away_team":{"id":20,"name":"Miami Dolphins","abbreviation":"MIA","logo_url":null,"badge_abbr":"MIA"}}}`

// iflCardSite is a stand-in for the site's private listener.
type iflCardSite struct {
	calls   atomic.Int32
	down    atomic.Bool
	garbled atomic.Bool
	delay   atomic.Int64 // ms
	mu      sync.Mutex
	viewers []string // ?viewer= of each news call
}

func newIFLCardSite(t *testing.T) *iflCardSite {
	t.Helper()
	s := &iflCardSite{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-IFL-Chat-Secret") != iflCardTestSecret {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		s.calls.Add(1)
		if d := s.delay.Load(); d > 0 {
			time.Sleep(time.Duration(d) * time.Millisecond)
		}
		if s.down.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		if s.garbled.Load() {
			io.WriteString(w, `<html>oops</html>`)
			return
		}
		switch r.URL.Path {
		case "/internal/chat/cards/score/4512":
			io.WriteString(w, iflScoreBody)
		case "/internal/chat/cards/news/rw-123":
			viewer := r.URL.Query().Get("viewer")
			s.mu.Lock()
			s.viewers = append(s.viewers, viewer)
			s.mu.Unlock()
			mine := "false"
			if viewer == "7201" {
				mine = "true"
			}
			io.WriteString(w, `{"item":{"id":"rw-123","title":"Herbert limited","content":"Ankle.","source":"RotoWire",`+
				`"published_at":"2026-11-25T15:00:00+00:00","player":{"id":9,"mfl_id":"13589","name":"Justin Herbert","position":"QB","nfl_team":"LAC"},`+
				`"owners":{"AFC":{"id":16,"abbreviation":"LAC","name":"Los Angeles Chargers","logo_url":null,"mine":`+mine+`,"badge_abbr":"LAC"}}}}`)
		default:
			w.WriteHeader(http.StatusNotFound)
			io.WriteString(w, `{"error":"Matchup not found"}`)
		}
	}))
	t.Cleanup(srv.Close)
	t.Setenv("IFL_SITE_INTERNAL_URL", srv.URL)
	t.Setenv("IFL_INTERNAL_SECRET", iflCardTestSecret)
	return s
}

func (s *iflCardSite) lastViewer() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.viewers[len(s.viewers)-1]
}

func iflGetCard(t *testing.T, c *model.Client4, path string) (string, *http.Response, error) {
	t.Helper()
	resp, err := c.DoAPIGet(context.Background(), path, "")
	if err != nil {
		return "", resp, err
	}
	defer resp.Body.Close()
	body, rerr := io.ReadAll(resp.Body)
	require.NoError(t, rerr)
	return string(body), resp, nil
}

func TestIFLCards(t *testing.T) {
	site := newIFLCardSite(t)
	th := Setup(t).InitBasic(t)

	t.Run("need a session", func(t *testing.T) {
		for _, path := range []string{"/ifl/cards/score/4512", "/ifl/cards/news/rw-123"} {
			_, resp, err := iflGetCard(t, th.CreateClient(), path)
			require.Error(t, err, path)
			require.Equal(t, http.StatusUnauthorized, resp.StatusCode, path)
		}
	})

	t.Run("score: the site's body unchanged, cached for 15 s", func(t *testing.T) {
		before := site.calls.Load()
		body, resp, err := iflGetCard(t, th.Client, "/ifl/cards/score/4512")
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, resp.StatusCode)
		require.JSONEq(t, iflScoreBody, body)
		require.Equal(t, "private, max-age=15", resp.Header.Get("Cache-Control"))

		_, _, err = iflGetCard(t, th.Client, "/ifl/cards/score/4512")
		require.NoError(t, err)
		require.Equal(t, before+1, site.calls.Load(), "the second read comes from the cache")
	})

	t.Run("score: no such game is 404, a malformed id never reaches the site", func(t *testing.T) {
		_, resp, err := iflGetCard(t, th.Client, "/ifl/cards/score/999")
		require.Error(t, err)
		require.Equal(t, http.StatusNotFound, resp.StatusCode)
		CheckErrorID(t, err, "ifl.cards.not_found")

		before := site.calls.Load()
		for _, path := range []string{"/ifl/cards/score/abc", "/ifl/cards/score/1234567890123", "/ifl/cards/score/-1"} {
			_, resp, err = iflGetCard(t, th.Client, path)
			require.Error(t, err, path)
			require.Equal(t, http.StatusNotFound, resp.StatusCode, path)
		}
		require.Equal(t, before, site.calls.Load())
	})

	t.Run("news: the viewer is the member's iflgm.com id, and part of the cache key", func(t *testing.T) {
		gm := iflGitlabUser(t, th, 7201)
		gmClient := iflSessionClient(t, th, gm)

		body, resp, err := iflGetCard(t, gmClient, "/ifl/cards/news/rw-123")
		require.NoError(t, err)
		require.Equal(t, "private, max-age=300", resp.Header.Get("Cache-Control"))
		require.Equal(t, "7201", site.lastViewer())
		var out struct {
			Item struct {
				ID     string `json:"id"`
				Owners map[string]struct {
					Mine      bool   `json:"mine"`
					BadgeAbbr string `json:"badge_abbr"`
				} `json:"owners"`
			} `json:"item"`
		}
		require.NoError(t, json.Unmarshal([]byte(body), &out))
		require.Equal(t, "rw-123", out.Item.ID)
		require.True(t, out.Item.Owners["AFC"].Mine)
		require.Equal(t, "LAC", out.Item.Owners["AFC"].BadgeAbbr)

		// A member who does not sign in through iflgm.com: no viewer, and
		// not the GM's cached answer.
		body, _, err = iflGetCard(t, th.Client, "/ifl/cards/news/rw-123")
		require.NoError(t, err)
		require.Equal(t, "", site.lastViewer())
		require.NoError(t, json.Unmarshal([]byte(body), &out))
		require.False(t, out.Item.Owners["AFC"].Mine)
	})

	t.Run("news: unknown story 404, malformed id 400", func(t *testing.T) {
		_, resp, err := iflGetCard(t, th.Client, "/ifl/cards/news/nope")
		require.Error(t, err)
		require.Equal(t, http.StatusNotFound, resp.StatusCode)
		CheckErrorID(t, err, "ifl.cards.not_found")

		_, resp, err = iflGetCard(t, th.Client, "/ifl/cards/news/"+"x1234567890123456789012345678901234567890")
		require.Error(t, err)
		require.Equal(t, http.StatusBadRequest, resp.StatusCode)
	})

	t.Run("site down or garbled: 502, and nothing bad is cached", func(t *testing.T) {
		site.down.Store(true)
		_, resp, err := iflGetCard(t, th.Client, "/ifl/cards/score/4513")
		require.Error(t, err)
		require.Equal(t, http.StatusBadGateway, resp.StatusCode)
		CheckErrorID(t, err, "ifl.cards.unavailable")
		site.down.Store(false)

		site.garbled.Store(true)
		_, resp, err = iflGetCard(t, th.Client, "/ifl/cards/news/rw-999")
		require.Error(t, err)
		require.Equal(t, http.StatusBadGateway, resp.StatusCode)
		CheckErrorID(t, err, "ifl.cards.unavailable")
		site.garbled.Store(false)

		// The failure was not kept: the next read asks the site again.
		_, resp, err = iflGetCard(t, th.Client, "/ifl/cards/score/4513")
		require.Error(t, err)
		require.Equal(t, http.StatusNotFound, resp.StatusCode)
	})

	t.Run("concurrent misses share one call", func(t *testing.T) {
		site.delay.Store(300)
		defer site.delay.Store(0)
		before := site.calls.Load()
		var wg sync.WaitGroup
		for range 5 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if resp, err := th.Client.DoAPIGet(context.Background(), "/ifl/cards/score/4514", ""); err == nil {
					resp.Body.Close()
				}
			}()
		}
		wg.Wait()
		require.Equal(t, before+1, site.calls.Load())
	})
}
