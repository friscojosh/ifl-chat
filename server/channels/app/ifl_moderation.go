// IFL: league chat fork (plan 8). Two moderation rules stock Mattermost does
// not have. Hooks: app/authorization.go (SessionHasPermissionToChannel),
// api4/post.go (deletePost) and app/post.go (UpdatePost).
package app

import (
	"net/http"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/request"
)

// iflMemberOnlyPermissions are the league moderator's permissions. The site's
// relay grants them to the commissioner through the team_admin role
// (ifl-website ops/chat/provision.sh), and a team role would otherwise reach
// every channel of the team. They apply only in channels the user belongs to;
// system admins are exempt (manage_system is checked before this rule).
var iflMemberOnlyPermissions = map[string]bool{
	model.PermissionEditOthersPosts.Id:                true,
	model.PermissionDeleteOthersPosts.Id:              true,
	model.PermissionManagePublicChannelProperties.Id:  true,
	model.PermissionManagePrivateChannelProperties.Id: true,
	model.PermissionDeletePublicChannel.Id:            true,
	model.PermissionDeletePrivateChannel.Id:           true,
}

// IFLDeletedRootMessage is what a thread's first message deleted while it
// had replies says from then on (marked model.PostPropsIFLDeletedRoot).
const IFLDeletedRootMessage = "(message deleted)"

// IFLIsDeletedRoot reports whether the post is a deleted thread root kept for
// its replies: the mark only IFLDeletePost sets, on a root that says
// IFLDeletedRootMessage. Such a post can no longer be edited.
func IFLIsDeletedRoot(post *model.Post) bool {
	deleted, _ := post.GetProp(model.PostPropsIFLDeletedRoot).(bool)
	return deleted && post.RootId == "" && post.Message == IFLDeletedRootMessage
}

// IFLDeletePost deletes a post as DeletePost does, except a thread's first
// message while the thread has replies: stock chat would delete every reply
// with it, other members' included. Instead the root keeps its place and its
// replies and loses everything else (text, files, props, pin): it reads
// "(message deleted)" in every client, and its thread stays whole.
func (a *App) IFLDeletePost(rctx request.CTX, post *model.Post, deleteByID string) (*model.Post, *model.AppError) {
	if post.RootId != "" || post.ReplyCount == 0 {
		return a.DeletePost(rctx, post.Id, deleteByID)
	}

	channel, appErr := a.GetChannel(rctx, post.ChannelId)
	if appErr != nil {
		return nil, appErr
	}
	if channel.DeleteAt != 0 {
		return nil, model.NewAppError("DeletePost", "api.post.delete_post.can_not_delete_post_in_deleted.error", nil, "", http.StatusBadRequest)
	}
	restrictDM, appErr := a.CheckIfChannelIsRestrictedDM(rctx, channel)
	if appErr != nil {
		return nil, appErr
	}
	if restrictDM {
		return nil, model.NewAppError("DeletePost", "api.post.delete_post.can_not_delete_from_restricted_dm.error", nil, "", http.StatusBadRequest)
	}

	kept := post.Clone()
	kept.Type = model.PostTypeDefault
	kept.Message = IFLDeletedRootMessage
	kept.MessageSource = ""
	kept.Hashtags = ""
	kept.FileIds = model.StringArray{}
	kept.IsPinned = false
	kept.Metadata = nil
	kept.SetProps(model.StringInterface{model.PostPropsIFLDeletedRoot: true})
	saved, err := a.Srv().Store().Post().Overwrite(rctx, kept)
	if err != nil {
		return nil, model.NewAppError("DeletePost", "app.post.delete.app_error", nil, "", http.StatusInternalServerError).Wrap(err)
	}

	if len(post.FileIds) > 0 {
		a.Srv().Go(func() {
			a.deletePostFiles(rctx, post.Id)
		})
		a.Srv().Store().FileInfo().InvalidateFileInfosForPostCache(post.Id, true)
		a.Srv().Store().FileInfo().InvalidateFileInfosForPostCache(post.Id, false)
	}
	a.invalidateCacheForChannelPosts(saved.ChannelId)

	forClients := a.PreparePostForClient(rctx, saved.Clone(), &model.PreparePostForClientOpts{IsEditPost: true})
	message := model.NewWebSocketEvent(model.WebsocketEventPostEdited, "", forClients.ChannelId, "", nil, "")
	if appErr := a.publishWebsocketEventForPost(rctx, forClients, message); appErr != nil {
		return nil, appErr
	}
	return saved, nil
}
