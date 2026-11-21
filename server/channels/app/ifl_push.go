// IFL: league chat fork (IFL Chat apps plan). ID-only push notifications in
// Team Edition. With PushNotificationContents=id_loaded, Apple and Google
// see only ids and a fixed line; the phone fetches the text from chat over
// TLS (POST /api/v4/notifications/ack), which calls GetNotificationMessage.
// Upstream allows this only with an Enterprise NotificationInterface; this
// registers our own through the official extension point.
package app

import (
	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/mlog"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/einterfaces"
)

func init() {
	RegisterNotificationInterface(func(a *App) einterfaces.NotificationInterface {
		return &iflNotification{app: a}
	})
}

type iflNotification struct{ app *App }

// CheckLicense: IFL Chat needs no licence for id-only push.
func (n *iflNotification) CheckLicense() *model.AppError { return nil }

// GetNotificationMessage is the full notification for one recipient, as
// sendPushNotification builds it with PushNotificationContents=full. The
// ack handler has already checked that userID may read the post
// (GetPostIfAuthorized in api4/system.go).
func (n *iflNotification) GetNotificationMessage(rctx request.CTX, ack *model.PushNotificationAck, userID string) (*model.PushNotification, *model.AppError) {
	a := n.app
	post, appErr := a.GetSinglePost(rctx, ack.PostId, false)
	if appErr != nil {
		return nil, appErr
	}
	channel, appErr := a.GetChannel(rctx, post.ChannelId)
	if appErr != nil {
		return nil, appErr
	}
	recipient, appErr := a.GetUser(rctx, userID)
	if appErr != nil {
		return nil, appErr
	}
	sender, appErr := a.GetUser(rctx, post.UserId)
	if appErr != nil {
		return nil, appErr
	}
	notification := &PostNotification{Post: post, Channel: channel, Sender: sender}
	if channel.Type == model.ChannelTypeGroup {
		profiles, err := a.Srv().Store().User().GetAllProfilesInChannel(rctx, channel.Id, true)
		if err != nil {
			rctx.Logger().Warn("IFL: group message members not loaded for a push title", mlog.String("channel_id", channel.Id), mlog.Err(err))
		} else {
			notification.ProfileMap = profiles
		}
	}
	nameFormat := a.GetNotificationNameFormat(recipient)
	channelName := notification.GetChannelName(nameFormat, recipient.Id)
	senderName := notification.GetSenderName(nameFormat, *a.Config().ServiceSettings.EnablePostUsernameOverride)
	replyToThreadType := ""
	if post.RootId != "" && a.IsCRTEnabledForUser(rctx, recipient.Id) {
		replyToThreadType = model.CommentsNotifyCRT
	}
	return a.buildFullPushNotificationMessage(rctx, model.FullNotification, post, recipient, channel,
		channelName, senderName, false, false, replyToThreadType), nil
}
