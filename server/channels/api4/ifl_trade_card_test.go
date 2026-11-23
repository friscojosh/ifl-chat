// IFL: league chat fork (trade cards in direct messages). The site's relay
// (a system admin) posts a trade offer as the proposing GM in their direct
// message with the other GM; nobody else may create, edit or delete a card.
package api4

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

type iflTradeCardResult struct {
	PostID    string `json:"post_id"`
	ChannelID string `json:"channel_id"`
	Adopted   bool   `json:"adopted"`
}

// iflTradeCardBody is what the relay sends for a trade offer.
func iflTradeCardBody(author, recipient string, tradeID int) map[string]any {
	return map[string]any{
		"author_id":    author,
		"recipient_id": recipient,
		"trade_id":     tradeID,
		"message":      "Trade offer",
		"type":         "custom_ifl_trade",
		"props": map[string]any{
			"ifl_trade_card": tradeID,
			"ifl_trade":      map[string]any{"id": tradeID, "status": "pending"},
			"attachments": []any{map[string]any{
				"text": "Trade offer",
				"actions": []any{map[string]any{
					"id": "accept", "name": "Accept", "type": "button",
					"integration": map[string]any{"url": "http://10.98.0.1:8081/internal/chat/trade/action", "context": map[string]any{"trade_id": tradeID}},
				}},
			}},
		},
	}
}

func iflPostTradeCard(t *testing.T, c *model.Client4, body any) (int, iflTradeCardResult) {
	t.Helper()
	resp, err := c.DoAPIPostJSON(context.Background(), "/ifl/trade_cards", body)
	if err != nil {
		require.NotNil(t, resp, "no response: %v", err)
		return resp.StatusCode, iflTradeCardResult{}
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	require.NoError(t, err)
	var out iflTradeCardResult
	require.NoError(t, json.Unmarshal(raw, &out), string(raw))
	return resp.StatusCode, out
}

func TestIFLTradeCardEndpoint(t *testing.T) {
	th := Setup(t).InitBasic(t)
	ctx := context.Background()
	author, _ := iflMember(t, th)
	recipient, recipientClient := iflMember(t, th)

	t.Run("refused for anyone but a system admin", func(t *testing.T) {
		status, _ := iflPostTradeCard(t, th.Client, iflTradeCardBody(author.Id, recipient.Id, 101))
		require.Equal(t, http.StatusForbidden, status)
		status, _ = iflPostTradeCard(t, recipientClient, iflTradeCardBody(author.Id, recipient.Id, 101))
		require.Equal(t, http.StatusForbidden, status)
	})

	var first iflTradeCardResult
	t.Run("posts the card as the author in the author's DM with the recipient", func(t *testing.T) {
		var status int
		status, first = iflPostTradeCard(t, th.SystemAdminClient, iflTradeCardBody(author.Id, recipient.Id, 101))
		require.Equal(t, http.StatusCreated, status)
		require.False(t, first.Adopted)
		require.True(t, model.IsValidId(first.PostID))

		post, appErr := th.App.GetSinglePost(th.Context, first.PostID, false)
		require.Nil(t, appErr)
		require.Equal(t, author.Id, post.UserId)
		require.Equal(t, first.ChannelID, post.ChannelId)
		require.Equal(t, "custom_ifl_trade", post.Type)
		require.Equal(t, "Trade offer", post.Message)
		require.EqualValues(t, 101, post.GetProp("ifl_trade_card"))
		require.NotNil(t, post.GetProp("ifl_trade"))
		require.Len(t, post.Attachments(), 1)
		require.Len(t, post.Attachments()[0].Actions, 1)

		channel, appErr := th.App.GetChannel(th.Context, post.ChannelId)
		require.Nil(t, appErr)
		require.Equal(t, model.ChannelTypeDirect, channel.Type)
		require.Equal(t, model.GetDMNameFromIds(author.Id, recipient.Id), channel.Name)

		// The recipient sees it, unread, in their DM.
		got, _, err := recipientClient.GetPost(ctx, first.PostID, "")
		require.NoError(t, err)
		require.Equal(t, author.Id, got.UserId)
		unread, _, err := recipientClient.GetChannelUnread(ctx, channel.Id, recipient.Id)
		require.NoError(t, err)
		require.EqualValues(t, 1, unread.MsgCount)
	})

	t.Run("a second delivery adopts the post already there", func(t *testing.T) {
		status, again := iflPostTradeCard(t, th.SystemAdminClient, iflTradeCardBody(author.Id, recipient.Id, 101))
		require.Equal(t, http.StatusOK, status)
		require.True(t, again.Adopted)
		require.Equal(t, first.PostID, again.PostID)
		require.Equal(t, first.ChannelID, again.ChannelID)

		list, _, err := th.SystemAdminClient.GetPostsForChannel(ctx, first.ChannelID, 0, 60, "", false, false)
		require.NoError(t, err)
		cards := 0
		for _, p := range list.Posts {
			if p.GetProp("ifl_trade_card") != nil {
				cards++
			}
		}
		require.Equal(t, 1, cards)
	})

	t.Run("another trade in the same DM is a new card", func(t *testing.T) {
		status, other := iflPostTradeCard(t, th.SystemAdminClient, iflTradeCardBody(author.Id, recipient.Id, 102))
		require.Equal(t, http.StatusCreated, status)
		require.False(t, other.Adopted)
		require.NotEqual(t, first.PostID, other.PostID)
		require.Equal(t, first.ChannelID, other.ChannelID)
	})

	t.Run("the same trade proposed by the other GM is their own card", func(t *testing.T) {
		status, theirs := iflPostTradeCard(t, th.SystemAdminClient, iflTradeCardBody(recipient.Id, author.Id, 101))
		require.Equal(t, http.StatusCreated, status)
		require.NotEqual(t, first.PostID, theirs.PostID)
		require.Equal(t, first.ChannelID, theirs.ChannelID)
	})

	t.Run("validation", func(t *testing.T) {
		deactivated, _ := iflMember(t, th)
		_, appErr := th.App.UpdateActive(th.Context, deactivated, false)
		require.Nil(t, appErr)

		for name, mutate := range map[string]func(b map[string]any){
			"wrong type":            func(b map[string]any) { b["type"] = "custom_other" },
			"no type":               func(b map[string]any) { delete(b, "type") },
			"card id differs":       func(b map[string]any) { b["props"].(map[string]any)["ifl_trade_card"] = 999 },
			"card id missing":       func(b map[string]any) { delete(b["props"].(map[string]any), "ifl_trade_card") },
			"card id is a string":   func(b map[string]any) { b["props"].(map[string]any)["ifl_trade_card"] = "101" },
			"card id is fractional": func(b map[string]any) { b["props"].(map[string]any)["ifl_trade_card"] = 101.5 },
			"no props":              func(b map[string]any) { delete(b, "props") },
			"no trade id":           func(b map[string]any) { delete(b, "trade_id") },
			"trade id is a string":  func(b map[string]any) { b["trade_id"] = "101" },
			"zero trade id": func(b map[string]any) {
				b["trade_id"] = 0
				b["props"].(map[string]any)["ifl_trade_card"] = 0
			},
			"same author and recipient": func(b map[string]any) { b["recipient_id"] = author.Id },
			"unknown author":            func(b map[string]any) { b["author_id"] = model.NewId() },
			"unknown recipient":         func(b map[string]any) { b["recipient_id"] = model.NewId() },
			"malformed author":          func(b map[string]any) { b["author_id"] = "nope" },
			"deactivated author":        func(b map[string]any) { b["author_id"] = deactivated.Id },
			"deactivated recipient":     func(b map[string]any) { b["recipient_id"] = deactivated.Id },
		} {
			t.Run(name, func(t *testing.T) {
				body := iflTradeCardBody(author.Id, recipient.Id, 101)
				mutate(body)
				status, _ := iflPostTradeCard(t, th.SystemAdminClient, body)
				require.Equal(t, http.StatusBadRequest, status)
			})
		}

		resp, err := th.SystemAdminClient.DoAPIPost(ctx, "/ifl/trade_cards", "{not json")
		require.Error(t, err)
		require.Equal(t, http.StatusBadRequest, resp.StatusCode)
	})
}

func TestIFLTradeCardLock(t *testing.T) {
	th := Setup(t).InitBasic(t)
	defer th.RestoreDefaultRolePermissions(t, th.SaveDefaultRolePermissions(t))
	iflApplyModerationRoles(t, th)
	ctx := context.Background()
	author, authorClient := iflMember(t, th)
	recipient, recipientClient := iflMember(t, th)

	newCard := func(t *testing.T, tradeID int) *model.Post {
		t.Helper()
		status, res := iflPostTradeCard(t, th.SystemAdminClient, iflTradeCardBody(author.Id, recipient.Id, tradeID))
		require.Equal(t, http.StatusCreated, status)
		post, appErr := th.App.GetSinglePost(th.Context, res.PostID, false)
		require.Nil(t, appErr)
		return post
	}
	card := newCard(t, 201)
	dm := card.ChannelId
	members := map[string]*model.Client4{"author": authorClient, "recipient": recipientClient}

	t.Run("members cannot post a trade card", func(t *testing.T) {
		for name, post := range map[string]*model.Post{
			"type":           {ChannelId: dm, Message: "fake", Type: "custom_ifl_trade"},
			"ifl_trade_card": {ChannelId: dm, Message: "fake", Props: model.StringInterface{"ifl_trade_card": 201}},
			"ifl_trade":      {ChannelId: dm, Message: "fake", Props: model.StringInterface{"ifl_trade": map[string]any{"id": 9}}},
		} {
			_, resp, err := authorClient.CreatePost(ctx, post)
			require.Error(t, err, name)
			CheckErrorID(t, err, "ifl.trade_card.locked")
			CheckForbiddenStatus(t, resp)
		}
		// Ordinary posts still go.
		_, resp, err := authorClient.CreatePost(ctx, &model.Post{ChannelId: dm, Message: "hello"})
		require.NoError(t, err)
		CheckCreatedStatus(t, resp)
	})

	t.Run("members cannot schedule a trade card", func(t *testing.T) {
		th.App.UpdateConfig(func(cfg *model.Config) { *cfg.ServiceSettings.ScheduledPosts = true })
		th.App.Srv().SetLicense(model.NewTestLicenseSKU(model.LicenseShortSkuProfessional))
		defer func() { _ = th.App.Srv().RemoveLicense() }()
		scheduled := &model.ScheduledPost{
			Draft:       model.Draft{CreateAt: model.GetMillis(), UserId: author.Id, ChannelId: dm, Message: "fake"},
			ScheduledAt: model.GetMillis() + 100000,
		}
		scheduled.SetProps(model.StringInterface{"ifl_trade_card": 201})
		_, resp, err := authorClient.CreateScheduledPost(ctx, scheduled)
		CheckErrorID(t, err, "ifl.trade_card.locked")
		CheckForbiddenStatus(t, resp)
	})

	t.Run("members cannot edit, patch or delete a trade card", func(t *testing.T) {
		msg := "accepted!"
		for name, c := range members {
			_, resp, err := c.PatchPost(ctx, card.Id, &model.PostPatch{Message: &msg})
			require.Error(t, err, name)
			CheckForbiddenStatus(t, resp)

			props := model.StringInterface{"ifl_trade_card": 201}
			_, resp, err = c.PatchPost(ctx, card.Id, &model.PostPatch{Props: &props})
			require.Error(t, err, name)
			CheckForbiddenStatus(t, resp)

			edited := card.Clone()
			edited.Message = msg
			_, resp, err = c.UpdatePost(ctx, card.Id, edited)
			require.Error(t, err, name)
			CheckForbiddenStatus(t, resp)

			resp, err = c.DeletePost(ctx, card.Id)
			require.Error(t, err, name)
			CheckForbiddenStatus(t, resp)
			if name == "author" {
				// Stock chat lets the author delete their own post; the lock does not.
				CheckErrorID(t, err, "ifl.trade_card.locked")
			}
		}
		got, appErr := th.App.GetSinglePost(th.Context, card.Id, false)
		require.Nil(t, appErr)
		require.Equal(t, "Trade offer", got.Message)
		require.Zero(t, got.DeleteAt)
	})

	t.Run("not even as the commissioner", func(t *testing.T) {
		_, err := th.SystemAdminClient.UpdateTeamMemberRoles(ctx, th.BasicTeam.Id, author.Id, "team_user team_admin")
		require.NoError(t, err)
		defer func() {
			_, err := th.SystemAdminClient.UpdateTeamMemberRoles(ctx, th.BasicTeam.Id, author.Id, "team_user")
			require.NoError(t, err)
		}()
		resp, err := authorClient.DeletePost(ctx, card.Id)
		CheckErrorID(t, err, "ifl.trade_card.locked")
		CheckForbiddenStatus(t, resp)
		msg := "moderated"
		_, resp, err = authorClient.PatchPost(ctx, card.Id, &model.PostPatch{Message: &msg})
		require.Error(t, err)
		CheckForbiddenStatus(t, resp)
	})

	t.Run("members cannot turn their own post into a trade card", func(t *testing.T) {
		own, _, err := authorClient.CreatePost(ctx, &model.Post{ChannelId: dm, Message: "mine"})
		require.NoError(t, err)

		props := model.StringInterface{"ifl_trade": map[string]any{"id": 1}}
		_, resp, err := authorClient.PatchPost(ctx, own.Id, &model.PostPatch{Props: &props})
		require.Error(t, err)
		CheckForbiddenStatus(t, resp)

		edited := own.Clone()
		edited.AddProp("ifl_trade_card", 201)
		_, resp, err = authorClient.UpdatePost(ctx, own.Id, edited)
		require.Error(t, err)
		CheckForbiddenStatus(t, resp)

		// Their ordinary post still edits and deletes.
		msg := "mine, edited"
		_, resp, err = authorClient.PatchPost(ctx, own.Id, &model.PostPatch{Message: &msg})
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		edited = own.Clone()
		edited.Message = "mine, updated"
		_, resp, err = authorClient.UpdatePost(ctx, own.Id, edited)
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		resp, err = authorClient.DeletePost(ctx, own.Id)
		require.NoError(t, err)
		CheckOKStatus(t, resp)
	})

	t.Run("reactions, replies, pins and flags stay open", func(t *testing.T) {
		_, resp, err := recipientClient.SaveReaction(ctx, &model.Reaction{UserId: recipient.Id, PostId: card.Id, EmojiName: "thumbsup"})
		require.NoError(t, err)
		CheckOKStatus(t, resp)

		_, resp, err = recipientClient.CreatePost(ctx, &model.Post{ChannelId: dm, RootId: card.Id, Message: "counter coming"})
		require.NoError(t, err)
		CheckCreatedStatus(t, resp)

		resp, err = authorClient.PinPost(ctx, card.Id)
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		pinned := false
		_, resp, err = authorClient.PatchPost(ctx, card.Id, &model.PostPatch{IsPinned: &pinned})
		require.NoError(t, err)
		CheckOKStatus(t, resp)

		_, err = recipientClient.UpdatePreferences(ctx, recipient.Id, model.Preferences{{
			UserId: recipient.Id, Category: model.PreferenceCategoryFlaggedPost, Name: card.Id, Value: "true",
		}})
		require.NoError(t, err)
	})

	t.Run("a system admin patches a card and the author stays", func(t *testing.T) {
		msg := "Trade accepted"
		props := model.StringInterface{"ifl_trade_card": 201, "ifl_trade": map[string]any{"id": 201, "status": "accepted"}}
		patched, resp, err := th.SystemAdminClient.PatchPost(ctx, card.Id, &model.PostPatch{Message: &msg, Props: &props})
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		require.Equal(t, author.Id, patched.UserId)
		require.Equal(t, "custom_ifl_trade", patched.Type)

		got, appErr := th.App.GetSinglePost(th.Context, card.Id, false)
		require.Nil(t, appErr)
		require.Equal(t, author.Id, got.UserId)
		require.Equal(t, msg, got.Message)
		require.Equal(t, "accepted", got.GetProp("ifl_trade").(map[string]any)["status"])

		// The author cannot restore the version from before the edit.
		history, _, err := authorClient.GetEditHistoryForPost(ctx, card.Id)
		require.NoError(t, err)
		require.NotEmpty(t, history)
		_, resp, err = authorClient.RestorePostVersion(ctx, card.Id, history[0].Id)
		CheckErrorID(t, err, "ifl.trade_card.locked")
		CheckForbiddenStatus(t, resp)

		// And the adoption still finds it after the edit.
		status, again := iflPostTradeCard(t, th.SystemAdminClient, iflTradeCardBody(author.Id, recipient.Id, 201))
		require.Equal(t, http.StatusOK, status)
		require.Equal(t, card.Id, again.PostID)
	})

	t.Run("a system admin deletes a card", func(t *testing.T) {
		doomed := newCard(t, 202)
		resp, err := th.SystemAdminClient.DeletePost(ctx, doomed.Id)
		require.NoError(t, err)
		CheckOKStatus(t, resp)
	})
}

// A button's response may change a trade card, or make a post one, only
// when the button is iflgm.com's own trade callback.
func TestIFLTradeCardButtonUpdate(t *testing.T) {
	th := Setup(t).InitBasic(t)
	ctx := context.Background()
	// Both servers answer every press by turning the post into accepted card 301.
	update := func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"update":{"message":"Trade accepted","props":{"ifl_trade_card":301,"ifl_trade":{"id":301,"status":"accepted"}}}}`))
	}
	site := httptest.NewServer(http.HandlerFunc(update))
	defer site.Close()
	elsewhere := httptest.NewServer(http.HandlerFunc(update))
	defer elsewhere.Close()
	t.Setenv("IFL_SITE_INTERNAL_URL", site.URL)
	t.Setenv("IFL_INTERNAL_SECRET", strings.Repeat("s", 40))
	th.App.UpdateConfig(func(cfg *model.Config) {
		*cfg.ServiceSettings.AllowedUntrustedInternalConnections = "localhost,127.0.0.1"
	})
	author, authorClient := iflMember(t, th)
	recipient, recipientClient := iflMember(t, th)

	withButton := func(body map[string]any, url string) map[string]any {
		props := body["props"].(map[string]any)
		props["attachments"].([]any)[0].(map[string]any)["actions"].([]any)[0].(map[string]any)["integration"].(map[string]any)["url"] = url
		return body
	}
	card := func(t *testing.T, tradeID int, url string) string {
		t.Helper()
		status, res := iflPostTradeCard(t, th.SystemAdminClient, withButton(iflTradeCardBody(author.Id, recipient.Id, tradeID), url))
		require.Equal(t, http.StatusCreated, status)
		return res.PostID
	}

	t.Run("the site's trade callback updates a card", func(t *testing.T) {
		id := card(t, 301, site.URL+"/internal/chat/trade/action")
		resp, err := recipientClient.DoPostAction(ctx, id, "accept")
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		got, appErr := th.App.GetSinglePost(th.Context, id, false)
		require.Nil(t, appErr)
		require.Equal(t, "Trade accepted", got.Message)
		require.Equal(t, author.Id, got.UserId)
	})

	t.Run("a button elsewhere cannot change a card", func(t *testing.T) {
		id := card(t, 302, elsewhere.URL+"/hook")
		resp, err := recipientClient.DoPostAction(ctx, id, "accept")
		CheckErrorID(t, err, "ifl.trade_card.locked")
		CheckForbiddenStatus(t, resp)
		got, appErr := th.App.GetSinglePost(th.Context, id, false)
		require.Nil(t, appErr)
		require.Equal(t, "Trade offer", got.Message)
	})

	t.Run("a member's own button cannot turn their post into a card", func(t *testing.T) {
		dm, _, err := authorClient.CreateDirectChannel(ctx, author.Id, recipient.Id)
		require.NoError(t, err)
		own, _, err := authorClient.CreatePost(ctx, &model.Post{
			ChannelId: dm.Id, Message: "press me",
			Props: model.StringInterface{model.PostPropsAttachments: []*model.MessageAttachment{{
				Text: "x",
				Actions: []*model.PostAction{{Id: "go", Name: "Go", Type: model.PostActionTypeButton,
					Integration: &model.PostActionIntegration{URL: elsewhere.URL + "/hook"}}},
			}}},
		})
		require.NoError(t, err)
		resp, err := authorClient.DoPostAction(ctx, own.Id, "go")
		CheckErrorID(t, err, "ifl.trade_card.locked")
		CheckForbiddenStatus(t, resp)
		got, appErr := th.App.GetSinglePost(th.Context, own.Id, false)
		require.Nil(t, appErr)
		require.Nil(t, got.GetProp("ifl_trade_card"))
	})
}
