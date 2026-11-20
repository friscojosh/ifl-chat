// IFL: league chat fork (plan 6).
package api4

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

// iflDial opens path with cookieToken as the chat session cookie and answers
// the authentication challenge with challengeToken.
func iflDial(t *testing.T, th *TestHelper, path, cookieToken, challengeToken string) *websocket.Conn {
	t.Helper()
	url := fmt.Sprintf("ws://localhost:%v%s%s", th.App.Srv().ListenAddr.Port, model.APIURLSuffix, path)
	header := http.Header{"Cookie": []string{model.SessionCookieToken + "=" + cookieToken}}
	conn, _, err := websocket.DefaultDialer.Dial(url, header)
	require.NoError(t, err)
	t.Cleanup(func() { conn.Close() })
	require.NoError(t, conn.WriteJSON(map[string]any{
		"seq": 1, "action": string(model.WebsocketAuthenticationChallenge), "data": map[string]any{"token": challengeToken},
	}))
	require.NoError(t, conn.SetReadDeadline(time.Now().Add(10*time.Second)))
	return conn
}

// iflHello is the connection's hello event: its user, sequence number and
// connection id.
type iflHello struct {
	UserID       string
	Seq          int64
	ConnectionID string
}

func iflReadHello(t *testing.T, conn *websocket.Conn) iflHello {
	t.Helper()
	for {
		var msg struct {
			Event string `json:"event"`
			Seq   int64  `json:"seq"`
			Data  struct {
				ConnectionID string `json:"connection_id"`
			} `json:"data"`
			Broadcast struct {
				UserID string `json:"user_id"`
			} `json:"broadcast"`
		}
		require.NoError(t, conn.ReadJSON(&msg))
		if msg.Event == string(model.WebsocketEventHello) {
			return iflHello{UserID: msg.Broadcast.UserID, Seq: msg.Seq, ConnectionID: msg.Data.ConnectionID}
		}
	}
}

// iflHelloUser returns the user the connection's hello event was sent to.
func iflHelloUser(t *testing.T, conn *websocket.Conn) string {
	t.Helper()
	return iflReadHello(t, conn).UserID
}

func TestIFLPanelWebSocket(t *testing.T) {
	th := Setup(t).InitBasic(t)
	cookieToken := th.Client.AuthToken // BasicUser, as if signed in to the full web client
	panel := th.CreateClient()
	_, _, err := panel.Login(context.Background(), th.BasicUser2.Username, th.BasicUser2.Password)
	require.NoError(t, err)

	t.Run("stock route binds the cookie session and ignores the challenge", func(t *testing.T) {
		conn := iflDial(t, th, "/websocket", cookieToken, panel.AuthToken)
		require.Equal(t, th.BasicUser.Id, iflHelloUser(t, conn))
	})

	t.Run("panel route binds the challenge session", func(t *testing.T) {
		conn := iflDial(t, th, "/ifl/websocket", cookieToken, panel.AuthToken)
		require.Equal(t, th.BasicUser2.Id, iflHelloUser(t, conn))
	})

	t.Run("panel route closes on an invalid challenge despite a valid cookie", func(t *testing.T) {
		conn := iflDial(t, th, "/ifl/websocket", cookieToken, "not-a-session-token")
		var msg map[string]any
		require.Error(t, conn.ReadJSON(&msg))
	})

	t.Run("panel route never resumes: every connection starts at sequence 0", func(t *testing.T) {
		first := iflReadHello(t, iflDial(t, th, "/ifl/websocket", cookieToken, panel.AuthToken))
		require.Equal(t, int64(0), first.Seq)
		again := iflReadHello(t, iflDial(t, th, "/ifl/websocket?connection_id="+first.ConnectionID+"&sequence_number=5", cookieToken, panel.AuthToken))
		require.Equal(t, int64(0), again.Seq)
		require.NotEqual(t, first.ConnectionID, again.ConnectionID)
	})
}
