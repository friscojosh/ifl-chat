// IFL: league chat fork (IFL Chat apps plan). The team chip routes.
package api4

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

const iflBadgeTestSecret = "internal-secret-internal-secret-badges"

var iflBadgeTestPNG = []byte("\x89PNG\r\n\x1a\nIFL")

// iflBadgeSite is a stand-in for the site's private listener. team is the
// abbreviation it lists for site user 7101; down makes it answer 503.
type iflBadgeSite struct {
	team atomic.Value
	down atomic.Bool
}

func newIFLBadgeSite(t *testing.T) *iflBadgeSite {
	t.Helper()
	s := &iflBadgeSite{}
	s.team.Store("LAC")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-IFL-Chat-Secret") != iflBadgeTestSecret {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if s.down.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		switch r.URL.Path {
		case "/internal/chat/team-badges":
			fmt.Fprintf(w, `{"version":"x","teams":[`+
				`{"abbr":"LAC","name":"Los Angeles Chargers","conference":"AFC","color":"#007BC7","logo_rev":"aa11"},`+
				`{"abbr":"MIA","name":"Miami Dolphins","conference":"AFC","color":"#008E97","logo_rev":"bb22"}],`+
				`"members":[{"site_user_id":7101,"abbr":%q},{"site_user_id":7102,"abbr":"LAC"}]}`, s.team.Load().(string))
		case "/internal/chat/team-logos/LAC.png":
			w.Write(iflBadgeTestPNG)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(srv.Close)
	t.Setenv("IFL_SITE_INTERNAL_URL", srv.URL)
	t.Setenv("IFL_INTERNAL_SECRET", iflBadgeTestSecret)
	return s
}

func iflGetBadges(t *testing.T, c *model.Client4, etag string) (ifl.Badges, *http.Response) {
	t.Helper()
	resp, err := c.DoAPIGet(context.Background(), "/ifl/team_badges", etag)
	var b ifl.Badges
	if err == nil && resp.StatusCode == http.StatusOK {
		defer resp.Body.Close()
		require.NoError(t, json.NewDecoder(resp.Body).Decode(&b))
	}
	return b, resp
}

func TestIFLTeamBadges(t *testing.T) {
	site := newIFLBadgeSite(t)
	th := Setup(t).InitBasic(t)
	gm := iflGitlabUser(t, th, 7101)
	gone := iflGitlabUser(t, th, 7102)
	_, appErr := th.App.UpdateActive(th.Context, gone, false)
	require.Nil(t, appErr)

	t.Run("needs a session", func(t *testing.T) {
		resp, err := th.CreateClient().DoAPIGet(context.Background(), "/ifl/team_badges", "")
		require.Error(t, err)
		require.Equal(t, http.StatusUnauthorized, resp.StatusCode)
	})

	t.Run("a GM's chip; deactivated and unlinked accounts have none", func(t *testing.T) {
		b, resp := iflGetBadges(t, th.Client, "")
		require.Equal(t, http.StatusOK, resp.StatusCode)
		require.Equal(t, map[string]string{gm.Id: "LAC"}, b.Users)
		require.Equal(t, "Los Angeles Chargers", b.Teams["LAC"].Name)
		require.Equal(t, "AFC", b.Teams["LAC"].Conference)
		require.Equal(t, b.Version, resp.Header.Get(model.HeaderEtagServer))
		require.Contains(t, resp.Header.Get("Cache-Control"), "private")
	})

	t.Run("a repeat with the version is 304", func(t *testing.T) {
		b, _ := iflGetBadges(t, th.Client, "")
		_, resp := iflGetBadges(t, th.Client, b.Version)
		require.Equal(t, http.StatusNotModified, resp.StatusCode)
	})

	t.Run("what a member can edit gives no chip", func(t *testing.T) {
		_, _, err := th.Client.PatchUser(context.Background(), th.BasicUser.Id, &model.UserPatch{
			Nickname: model.NewPointer("LAC"), Position: model.NewPointer("Los Angeles Chargers"),
			Props: model.StringMap{"team": "LAC", "abbr": "LAC"},
		})
		require.NoError(t, err)
		_, err = th.SystemAdminClient.DoAPIPost(context.Background(), "/ifl/team_badges/refresh", "")
		require.NoError(t, err)
		b, _ := iflGetBadges(t, th.Client, "")
		require.NotContains(t, b.Users, th.BasicUser.Id)
	})

	t.Run("refresh is for system admins; a change reaches open clients", func(t *testing.T) {
		resp, err := th.Client.DoAPIPost(context.Background(), "/ifl/team_badges/refresh", "")
		require.Error(t, err)
		require.Equal(t, http.StatusForbidden, resp.StatusCode)

		ws := th.CreateConnectedWebSocketClient(t)
		site.team.Store("MIA")
		resp, err = th.SystemAdminClient.DoAPIPost(context.Background(), "/ifl/team_badges/refresh", "")
		require.NoError(t, err)
		var out struct {
			Version string `json:"version"`
			Changed bool   `json:"changed"`
		}
		require.NoError(t, json.NewDecoder(resp.Body).Decode(&out))
		require.True(t, out.Changed)

		deadline := time.After(10 * time.Second)
		for got := false; !got; {
			select {
			case ev := <-ws.EventChannel:
				if ev.EventType() == "custom_ifl_team_badges_changed" {
					require.Equal(t, out.Version, ev.GetData()["version"])
					got = true
				}
			case <-deadline:
				t.Fatal("no custom_ifl_team_badges_changed event")
			}
		}
		b, _ := iflGetBadges(t, th.Client, "")
		require.Equal(t, "MIA", b.Users[gm.Id])

		resp, err = th.SystemAdminClient.DoAPIPost(context.Background(), "/ifl/team_badges/refresh", "")
		require.NoError(t, err)
		require.NoError(t, json.NewDecoder(resp.Body).Decode(&out))
		require.False(t, out.Changed)
	})

	t.Run("logos need no session; unknown teams are 404", func(t *testing.T) {
		site.team.Store("LAC")
		anon := th.CreateClient()
		resp, err := anon.DoAPIGet(context.Background(), "/ifl/team_badges/logos/LAC.png?s=64&v=aa11", "")
		require.NoError(t, err)
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)
		require.Equal(t, iflBadgeTestPNG, body)
		require.Equal(t, "image/png", resp.Header.Get("Content-Type"))
		require.True(t, strings.Contains(resp.Header.Get("Cache-Control"), "immutable"))
		for _, path := range []string{"/ifl/team_badges/logos/NYJ.png", "/ifl/team_badges/logos/lac.png"} {
			resp, err = anon.DoAPIGet(context.Background(), path, "")
			require.Error(t, err, path)
			require.Equal(t, http.StatusNotFound, resp.StatusCode, path)
		}
	})

	t.Run("site unreachable: the last good badges stay", func(t *testing.T) {
		before, _ := iflGetBadges(t, th.Client, "")
		site.down.Store(true)
		defer site.down.Store(false)
		resp, err := th.SystemAdminClient.DoAPIPost(context.Background(), "/ifl/team_badges/refresh", "")
		require.Error(t, err)
		require.Equal(t, http.StatusBadGateway, resp.StatusCode)
		CheckErrorID(t, err, "ifl.team_badges.unavailable")
		after, _ := iflGetBadges(t, th.Client, "")
		require.Equal(t, before.Users, after.Users)
	})
}
