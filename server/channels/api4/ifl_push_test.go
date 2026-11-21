// IFL: league chat fork (IFL Chat apps plan). ID-only push in Team Edition.
package api4

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

// iflAck is what a phone sends when an id-only push arrives.
func iflAck(t *testing.T, c *model.Client4, postID string) (*model.PushNotification, *http.Response) {
	t.Helper()
	body := fmt.Sprintf(`{"id":"ack1","is_id_loaded":true,"platform":"android","post_id":%q,"type":%q}`, postID, model.PushTypeMessage)
	resp, err := c.DoAPIPost(context.Background(), "/notifications/ack", body)
	if err != nil {
		return nil, resp
	}
	defer resp.Body.Close()
	var msg model.PushNotification
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&msg))
	return &msg, resp
}

func TestIFLIDLoadedPush(t *testing.T) {
	th := Setup(t).InitBasic(t)
	th.App.UpdateConfig(func(cfg *model.Config) {
		*cfg.ServiceSettings.CollapsedThreads = model.CollapsedThreadsAlwaysOn
		*cfg.ServiceSettings.ThreadAutoFollow = true
	})
	// The recipient: BasicUser2, a member of the basic channel.
	client2 := th.CreateClient()
	th.LoginBasic2WithClient(t, client2)

	t.Run("the payload carries ids and a fixed line, no text", func(t *testing.T) {
		post := th.CreatePostWithClient(t, th.Client, th.BasicChannel)
		msg, appErr := th.App.BuildPushNotificationMessage(th.Context, model.IdLoadedNotification, post, th.BasicUser2,
			th.BasicChannel, th.BasicChannel.DisplayName, "@"+th.BasicUser.Username, false, false, "")
		require.Nil(t, appErr)
		require.True(t, msg.IsIdLoaded)
		require.Equal(t, "New message in IFL Chat", msg.Message)
		require.NotContains(t, msg.Message, post.Message)
		require.Empty(t, msg.ChannelName)
		require.Empty(t, msg.SenderName)
		require.Equal(t, post.Id, msg.PostId)
		require.Equal(t, th.BasicChannel.Id, msg.ChannelId)
	})

	t.Run("the app fetches a channel post's text", func(t *testing.T) {
		post := th.CreatePostWithClient(t, th.Client, th.BasicChannel)
		msg, resp := iflAck(t, client2, post.Id)
		require.Equal(t, http.StatusOK, resp.StatusCode)
		require.False(t, msg.IsIdLoaded)
		require.Equal(t, post.Id, msg.PostId)
		require.Equal(t, th.BasicChannel.Id, msg.ChannelId)
		require.Equal(t, th.BasicUser.Id, msg.SenderId)
		require.Equal(t, th.BasicChannel.DisplayName, msg.ChannelName)
		require.True(t, strings.HasSuffix(msg.Message, ": "+post.Message), msg.Message)
	})

	t.Run("a direct message", func(t *testing.T) {
		dm := th.CreateDmChannel(t, th.BasicUser2)
		post := th.CreatePostWithClient(t, th.Client, dm)
		msg, resp := iflAck(t, client2, post.Id)
		require.Equal(t, http.StatusOK, resp.StatusCode)
		require.Equal(t, post.Message, msg.Message)
		require.True(t, strings.HasPrefix(msg.ChannelName, "@"), msg.ChannelName)
	})

	t.Run("a thread reply with collapsed threads", func(t *testing.T) {
		root := th.CreatePostWithClient(t, th.Client, th.BasicChannel)
		reply, _, err := th.Client.CreatePost(context.Background(), &model.Post{ChannelId: th.BasicChannel.Id, RootId: root.Id, Message: "reply " + model.NewId()})
		require.NoError(t, err)
		msg, resp := iflAck(t, client2, reply.Id)
		require.Equal(t, http.StatusOK, resp.StatusCode)
		require.Equal(t, root.Id, msg.RootId)
		require.True(t, msg.IsCRTEnabled)
		require.Contains(t, msg.ChannelName, th.BasicChannel.DisplayName)
		require.True(t, strings.HasSuffix(msg.Message, ": "+reply.Message), msg.Message)
	})

	t.Run("a post the member cannot read is refused", func(t *testing.T) {
		private := th.CreateChannelWithClient(t, th.SystemAdminClient, model.ChannelTypePrivate)
		post := th.CreatePostWithClient(t, th.SystemAdminClient, private)
		_, resp := iflAck(t, th.Client, post.Id)
		require.Equal(t, http.StatusForbidden, resp.StatusCode)
	})
}
