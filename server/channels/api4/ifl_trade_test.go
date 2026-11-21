// IFL: league chat fork (plan 9). Tests for /trade and the signing of trade
// callbacks to iflgm.com.
package api4

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

type iflSiteCall struct {
	path, secret, siteUser string
	body                   map[string]any
}

// iflSessionClient signs a site-linked member in the way a GitLab sign-in
// does: with a session of their own (they have no password).
func iflSessionClient(t *testing.T, th *TestHelper, user *model.User) *model.Client4 {
	t.Helper()
	session, appErr := th.App.CreateSession(th.Context, &model.Session{UserId: user.Id, Roles: user.GetRawRoles()})
	require.Nil(t, appErr)
	client := th.CreateClient()
	client.SetToken(session.Token)
	return client
}

func iflButtonPost(t *testing.T, th *TestHelper, url string) *model.Post {
	t.Helper()
	post, _, appErr := th.App.CreatePost(th.Context, &model.Post{
		UserId: th.BasicUser.Id, ChannelId: th.BasicChannel.Id, Message: "trade card",
		Props: model.StringInterface{model.PostPropsAttachments: []*model.MessageAttachment{{
			Text: "buttons",
			Actions: []*model.PostAction{{Id: "accept", Name: "Accept", Type: model.PostActionTypeButton,
				Integration: &model.PostActionIntegration{URL: url, Context: map[string]any{"trade_id": 1}}}},
		}}},
	}, th.BasicChannel, model.CreatePostFlags{})
	require.Nil(t, appErr)
	return post
}

func TestIFLTrade(t *testing.T) {
	th := Setup(t).InitBasic(t)
	ctx := context.Background()
	secret := strings.Repeat("s", 40)
	calls := make(chan iflSiteCall, 8)
	leaked := make(chan string, 8)
	elsewhere := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		leaked <- r.Header.Get("X-IFL-Chat-Secret")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer elsewhere.Close()
	var redirectTo atomic.Value // string: the site answers the next button press with a redirect there
	redirectTo.Store("")
	site := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		calls <- iflSiteCall{r.URL.Path, r.Header.Get("X-IFL-Chat-Secret"), r.Header.Get("X-IFL-Site-User"), body}
		if to := redirectTo.Load().(string); to != "" {
			http.Redirect(w, r, to, http.StatusTemporaryRedirect)
			return
		}
		if r.URL.Path == "/internal/chat/trade/command" {
			_, _ = w.Write([]byte(`{"text":"Choose a partner"}`))
			return
		}
		_, _ = w.Write([]byte(`{}`))
	}))
	defer site.Close()
	t.Setenv("IFL_SITE_INTERNAL_URL", site.URL)
	t.Setenv("IFL_INTERNAL_SECRET", secret)
	th.App.UpdateConfig(func(cfg *model.Config) {
		*cfg.ServiceSettings.EnableCommands = false // as in production: custom commands stay off
		*cfg.ServiceSettings.AllowedUntrustedInternalConnections = "localhost,127.0.0.1"
	})

	gm := iflGitlabUser(t, th, 16)
	th.LinkUserToTeam(t, gm, th.BasicTeam)
	th.AddUserToChannel(t, gm, th.BasicChannel)
	gmClient := iflSessionClient(t, th, gm)

	next := func() iflSiteCall {
		select {
		case c := <-calls:
			return c
		case <-time.After(5 * time.Second):
			t.Fatal("the site was not called")
			return iflSiteCall{}
		}
	}
	none := func() {
		select {
		case c := <-calls:
			t.Fatalf("unexpected site call %s", c.path)
		default:
		}
	}

	t.Run("/trade forwards the member's site id and returns the trigger id", func(t *testing.T) {
		resp, _, err := gmClient.ExecuteCommand(ctx, th.BasicChannel.Id, "/trade MIA")
		require.NoError(t, err)
		require.Equal(t, "Choose a partner", resp.Text)
		require.NotEmpty(t, resp.TriggerId, "the client opens the site's dialog only for this trigger id")
		call := next()
		require.Equal(t, "/internal/chat/trade/command", call.path)
		require.Equal(t, secret, call.secret)
		require.Equal(t, "16", call.siteUser)
		require.Equal(t, "MIA", call.body["text"])
		require.NotEmpty(t, call.body["trigger_id"])
	})

	t.Run("with custom commands off, only the allowlisted built-ins run", func(t *testing.T) {
		for _, command := range []string{"/away", "/online", "/offline", "/dnd", "/me waves", "/shrug",
			"/msg @" + th.BasicUser2.Username + " hello", "/mute", "/mute", "/expand", "/collapse", "/help"} {
			_, _, err := th.Client.ExecuteCommand(ctx, th.BasicChannel.Id, command)
			require.NoError(t, err, command)
		}
		for _, command := range []string{"/echo later 600", "/kick @" + th.BasicUser2.Username,
			"/remove @" + th.BasicUser2.Username, "/invite @" + gm.Username + " ~" + th.BasicChannel2.Name,
			"/join ~" + th.BasicPrivateChannel.Name, "/leave", "/header new header", "/purpose new purpose",
			"/rename renamed", "/groupmsg @" + th.BasicUser2.Username + ",@" + gm.Username + " hi",
			"/code x", "/search x", "/settings", "/logout", "/nosuchcommand"} {
			_, resp, err := gmClient.ExecuteCommand(ctx, th.BasicChannel.Id, command)
			require.Error(t, err, command)
			CheckNotImplementedStatus(t, resp)
		}
		member, appErr := th.App.GetChannelMember(th.Context, th.BasicChannel.Id, th.BasicUser2.Id)
		require.Nil(t, appErr, "/kick did not run")
		require.NotNil(t, member)
		_, appErr = th.App.GetChannelMember(th.Context, th.BasicPrivateChannel.Id, gm.Id)
		require.NotNil(t, appErr, "/join did not run")
		_, resp, err := th.SystemAdminClient.CreateCommand(ctx, &model.Command{TeamId: th.BasicTeam.Id, URL: "http://nowhere.example", Method: model.CommandMethodPost, Trigger: "mine"})
		require.Error(t, err)
		CheckNotImplementedStatus(t, resp)
		none()
	})

	t.Run("autocomplete offers only the built-ins that run", func(t *testing.T) {
		commands, _, err := th.Client.ListAutocompleteCommands(ctx, th.BasicTeam.Id)
		require.NoError(t, err)
		triggers := map[string]bool{}
		for _, c := range commands {
			triggers[c.Trigger] = true
		}
		require.True(t, triggers["trade"] && triggers["away"] && triggers["msg"], "%v", triggers)
		require.False(t, triggers["echo"] || triggers["kick"] || triggers["invite"] || triggers["join"], "%v", triggers)
	})

	t.Run("a member who does not sign in with iflgm.com is told so; the site hears nothing", func(t *testing.T) {
		resp, _, err := th.Client.ExecuteCommand(ctx, th.BasicChannel.Id, "/trade")
		require.NoError(t, err)
		require.Contains(t, resp.Text, "Only members who sign in with iflgm.com")
		none()
	})

	t.Run("a button on the trade path carries the secret and the presser's site id", func(t *testing.T) {
		post := iflButtonPost(t, th, site.URL+"/internal/chat/trade/action")
		_, err := gmClient.DoPostActionWithCookie(ctx, post.Id, "accept", "", "", nil, "")
		require.NoError(t, err)
		call := next()
		require.Equal(t, "/internal/chat/trade/action", call.path)
		require.Equal(t, secret, call.secret)
		require.Equal(t, "16", call.siteUser)
		require.Equal(t, gm.Id, call.body["user_id"])
	})

	t.Run("an unlinked presser gets no site id", func(t *testing.T) {
		post := iflButtonPost(t, th, site.URL+"/internal/chat/trade/action")
		_, err := th.Client.DoPostActionWithCookie(ctx, post.Id, "accept", "", "", nil, "")
		require.NoError(t, err)
		call := next()
		require.Equal(t, secret, call.secret)
		require.Empty(t, call.siteUser)
	})

	t.Run("a signed request follows no redirect, so the secret goes nowhere else", func(t *testing.T) {
		post := iflButtonPost(t, th, site.URL+"/internal/chat/trade/action")
		redirectTo.Store(elsewhere.URL + "/collect")
		defer redirectTo.Store("")
		_, err := gmClient.DoPostActionWithCookie(ctx, post.Id, "accept", "", "", nil, "")
		call := next()
		require.Equal(t, secret, call.secret)
		require.Error(t, err, "chat reports the redirect as a failed action")
		select {
		case got := <-leaked:
			t.Fatalf("the redirect was followed (secret sent: %t)", got != "")
		case <-time.After(500 * time.Millisecond):
		}
	})

	t.Run("a button to any other private path never carries the secret", func(t *testing.T) {
		post := iflButtonPost(t, th, site.URL+"/internal/chat/users/16/suspension")
		_, _ = gmClient.DoPostActionWithCookie(ctx, post.Id, "accept", "", "", nil, "")
		call := next()
		require.Equal(t, "/internal/chat/users/16/suspension", call.path)
		require.Empty(t, call.secret)
		require.Empty(t, call.siteUser)
	})
}
