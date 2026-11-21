// IFL: league chat fork (plan 8). Commissioner moderation: ops/chat/provision.sh
// (ifl-website, branch ops/chat-infrastructure) sets the built-in team_admin
// role to exactly the moderator allowlist, the site's relay makes each
// eligible commissioner a team admin of the league team, and two fork rules
// (app/ifl_moderation.go) keep that authority to the channels the moderator
// is in and keep a thread's replies when its first message is deleted. These
// tests set the same allowlist through the same role API and show that chat
// itself refuses what the iflgm.com panel merely hides.
package api4

import (
	"context"
	"slices"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

// iflModeratorPermissions is team_admin's complete permission list after
// provision.sh (MODERATOR_PERMISSIONS there and in the site's
// api/app/chat/relay.py). Keep the three in step. A commissioner is
// also team_user in the team and channel_user in each channel they belong to,
// so own-post edits, create_post and reading come from those roles; the
// moderator role adds only what a member lacks.
var iflModeratorPermissions = []string{"delete_others_posts", "edit_others_posts"}

// iflApplyModerationRoles replaces team_admin's permissions with the
// allowlist, as provision.sh does: whatever the role held before (stock
// grants, or grants a permissions migration added) is dropped.
func iflApplyModerationRoles(t *testing.T, th *TestHelper) {
	t.Helper()
	ctx := context.Background()
	for _, p := range iflModeratorPermissions {
		require.True(t, slices.ContainsFunc(model.AllPermissions, func(k *model.Permission) bool { return k.Id == p }),
			"provision.sh names an unknown permission %q", p)
	}
	role, _, err := th.SystemAdminClient.GetRoleByName(ctx, model.TeamAdminRoleId)
	require.NoError(t, err)
	perms := slices.Clone(iflModeratorPermissions)
	_, _, err = th.SystemAdminClient.PatchRole(ctx, role.Id, &model.RolePatch{Permissions: &perms})
	require.NoError(t, err)
}

// iflMember is a GM: a plain member of the team and of each channel, signed
// in on a client of their own.
func iflMember(t *testing.T, th *TestHelper, channels ...*model.Channel) (*model.User, *model.Client4) {
	t.Helper()
	user := th.CreateUser(t)
	th.LinkUserToTeam(t, user, th.BasicTeam)
	for _, ch := range channels {
		th.AddUserToChannel(t, user, ch)
	}
	client := th.CreateClient()
	_, _, err := client.Login(context.Background(), user.Email, user.Password)
	require.NoError(t, err)
	return user, client
}

func TestIFLCommissionerModeration(t *testing.T) {
	th := Setup(t).InitBasic(t)
	defer th.RestoreDefaultRolePermissions(t, th.SaveDefaultRolePermissions(t))
	iflApplyModerationRoles(t, th)
	ctx := context.Background()

	// BasicUser creates every channel, so is their channel admin, and writes
	// the posts being moderated. The commissioner is in `open` and `private`,
	// not in `elsewhere` (public) or `secret` (private).
	open := th.CreateChannelWithClient(t, th.Client, model.ChannelTypeOpen)
	private := th.CreateChannelWithClient(t, th.Client, model.ChannelTypePrivate)
	elsewhere := th.CreateChannelWithClient(t, th.Client, model.ChannelTypeOpen)
	secret := th.CreateChannelWithClient(t, th.Client, model.ChannelTypePrivate)
	gm, gmClient := iflMember(t, th, open, private)
	commissioner, commissionerClient := iflMember(t, th, open, private)

	edit := func(c *model.Client4, p *model.Post) *model.Response {
		msg := "edited by moderation"
		_, resp, _ := c.PatchPost(ctx, p.Id, &model.PostPatch{Message: &msg})
		return resp
	}
	remove := func(c *model.Client4, p *model.Post) *model.Response {
		resp, _ := c.DeletePost(ctx, p.Id)
		return resp
	}
	post := func(c *model.Client4, ch *model.Channel, rootID string) *model.Post {
		p, resp, err := c.CreatePost(ctx, &model.Post{ChannelId: ch.Id, RootId: rootID, Message: "post " + model.NewId()})
		require.NoError(t, err)
		CheckCreatedStatus(t, resp)
		return p
	}
	// What the relay does (PUT /teams/{team}/members/{user}/roles).
	setModerator := func(u *model.User, on bool) {
		roles := "team_user"
		if on {
			roles = "team_user team_admin"
		}
		_, err := th.SystemAdminClient.UpdateTeamMemberRoles(ctx, th.BasicTeam.Id, u.Id, roles)
		require.NoError(t, err)
	}

	t.Run("a GM cannot edit or delete another member's post", func(t *testing.T) {
		for _, ch := range []*model.Channel{open, private} {
			p := th.CreatePostWithClient(t, th.Client, ch)
			CheckForbiddenStatus(t, edit(gmClient, p))
			CheckForbiddenStatus(t, remove(gmClient, p))
		}
	})

	t.Run("a GM edits and deletes their own post", func(t *testing.T) {
		own := th.CreatePostWithClient(t, gmClient, open)
		CheckOKStatus(t, edit(gmClient, own))
		CheckOKStatus(t, remove(gmClient, own))
	})

	t.Run("the commissioner, a team admin, edits and deletes anyone's post in their channels", func(t *testing.T) {
		setModerator(commissioner, true)
		for _, ch := range []*model.Channel{open, private} {
			p := th.CreatePostWithClient(t, th.Client, ch)
			CheckOKStatus(t, edit(commissionerClient, p))
			CheckOKStatus(t, remove(commissionerClient, p))
		}
	})

	t.Run("not in channels they are not in, public or private", func(t *testing.T) {
		setModerator(commissioner, true)
		defer setModerator(commissioner, false)
		for _, ch := range []*model.Channel{elsewhere, secret} {
			p := th.CreatePostWithClient(t, th.Client, ch)
			CheckForbiddenStatus(t, edit(commissionerClient, p))
			CheckForbiddenStatus(t, remove(commissionerClient, p))
			// A system admin is exempt (manage_system), member or not.
			CheckOKStatus(t, remove(th.SystemAdminClient, p))
		}
	})

	t.Run("not in direct or group messages, even their own", func(t *testing.T) {
		setModerator(commissioner, true)
		defer setModerator(commissioner, false)
		dm, _, err := commissionerClient.CreateDirectChannel(ctx, commissioner.Id, th.BasicUser.Id)
		require.NoError(t, err)
		group, _, err := commissionerClient.CreateGroupChannel(ctx, []string{commissioner.Id, th.BasicUser.Id, gm.Id})
		require.NoError(t, err)
		for _, ch := range []*model.Channel{dm, group} {
			p := post(th.Client, ch, "")
			CheckForbiddenStatus(t, edit(commissionerClient, p))
			CheckForbiddenStatus(t, remove(commissionerClient, p))
		}
	})

	t.Run("a demotion applies to the session already open", func(t *testing.T) {
		setModerator(commissioner, false)
		p := th.CreatePostWithClient(t, th.Client, open)
		CheckForbiddenStatus(t, edit(commissionerClient, p))
		CheckForbiddenStatus(t, remove(commissionerClient, p))
	})

	// What a reply-keeping delete leaves: the root, now "(message deleted)",
	// and every reply that was there.
	requireKept := func(t *testing.T, root *model.Post, replies ...*model.Post) {
		t.Helper()
		got, _, err := gmClient.GetPost(ctx, root.Id, "")
		require.NoError(t, err)
		require.Equal(t, "(message deleted)", got.Message)
		require.Equal(t, true, got.GetProp("ifl_deleted_root"))
		require.Empty(t, got.FileIds)
		require.Zero(t, got.DeleteAt)
		thread, _, err := gmClient.GetPostThread(ctx, root.Id, "", false)
		require.NoError(t, err)
		want := []string{root.Id}
		for _, r := range replies {
			want = append(want, r.Id)
		}
		require.ElementsMatch(t, want, thread.Order)
	}

	t.Run("deleting a thread's first message keeps everyone's replies", func(t *testing.T) {
		root := post(gmClient, open, "")
		theirs := post(th.Client, open, root.Id)
		mine := post(gmClient, open, root.Id)
		CheckOKStatus(t, remove(gmClient, root))
		requireKept(t, root, theirs, mine)
		// It stays deleted: its author cannot edit it back.
		CheckBadRequestStatus(t, edit(gmClient, root))
		// Replies are still ordinary posts.
		CheckOKStatus(t, remove(gmClient, mine))
		requireKept(t, root, theirs)
	})

	t.Run("the same when every reply is the author's own", func(t *testing.T) {
		root := post(gmClient, open, "")
		reply := post(gmClient, open, root.Id)
		CheckOKStatus(t, remove(gmClient, root))
		requireKept(t, root, reply)
	})

	t.Run("the same when the commissioner deletes it", func(t *testing.T) {
		setModerator(commissioner, true)
		defer setModerator(commissioner, false)
		root := post(th.Client, open, "")
		reply := post(gmClient, open, root.Id)
		CheckOKStatus(t, remove(commissionerClient, root))
		requireKept(t, root, reply)
	})

	t.Run("a first message without replies is deleted outright", func(t *testing.T) {
		root := post(gmClient, open, "")
		CheckOKStatus(t, remove(gmClient, root))
		_, resp, _ := gmClient.GetPost(ctx, root.Id, "")
		CheckNotFoundStatus(t, resp)
	})

	// Only the server's reply-keeping delete marks a root as deleted. A
	// member who could set the mark would make their post uneditable, even by
	// the commissioner, and hide it in the panel while other clients show it.
	t.Run("a client cannot set or keep the deleted-root mark", func(t *testing.T) {
		forged := func() model.StringInterface { return model.StringInterface{"ifl_deleted_root": true, "kept": "yes"} }
		requireUnmarked := func(t *testing.T, p *model.Post) {
			t.Helper()
			got, _, err := gmClient.GetPost(ctx, p.Id, "")
			require.NoError(t, err)
			require.Nil(t, got.GetProp("ifl_deleted_root"))
		}

		// Create: a root, and a reply.
		created, resp, err := gmClient.CreatePost(ctx, &model.Post{ChannelId: open.Id, Message: "(message deleted)", Props: forged()})
		require.NoError(t, err)
		CheckCreatedStatus(t, resp)
		require.Nil(t, created.GetProp("ifl_deleted_root"))
		require.Equal(t, "yes", created.GetProp("kept"))
		requireUnmarked(t, created)
		reply, _, err := gmClient.CreatePost(ctx, &model.Post{ChannelId: open.Id, RootId: created.Id, Message: "(message deleted)", Props: forged()})
		require.NoError(t, err)
		requireUnmarked(t, reply)

		// Update (PUT /posts/{id}).
		own := post(gmClient, open, "")
		own.Message = "(message deleted)"
		own.SetProps(forged())
		updated, resp, err := gmClient.UpdatePost(ctx, own.Id, own)
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		require.Nil(t, updated.GetProp("ifl_deleted_root"))
		requireUnmarked(t, own)

		// Patch (PUT /posts/{id}/patch), on a post with replies.
		props := forged()
		msg := "(message deleted)"
		patched, resp, err := gmClient.PatchPost(ctx, created.Id, &model.PostPatch{Message: &msg, Props: &props})
		require.NoError(t, err)
		CheckOKStatus(t, resp)
		require.Nil(t, patched.GetProp("ifl_deleted_root"))
		requireUnmarked(t, created)

		// So the post stays an ordinary one: its author and the commissioner
		// can still edit it.
		CheckOKStatus(t, edit(gmClient, created))
		setModerator(commissioner, true)
		defer setModerator(commissioner, false)
		CheckOKStatus(t, edit(commissionerClient, created))
		CheckOKStatus(t, edit(commissionerClient, own))
	})

	t.Run("the moderator role is exactly the allowlist and grants nothing else", func(t *testing.T) {
		role, _, err := th.SystemAdminClient.GetRoleByName(ctx, model.TeamAdminRoleId)
		require.NoError(t, err)
		require.ElementsMatch(t, iflModeratorPermissions, role.Permissions)

		setModerator(commissioner, true)
		defer setModerator(commissioner, false)
		// No making moderators, no removing members.
		resp, _ := commissionerClient.UpdateTeamMemberRoles(ctx, th.BasicTeam.Id, gm.Id, "team_user team_admin")
		CheckForbiddenStatus(t, resp)
		resp, _ = commissionerClient.RemoveTeamMember(ctx, th.BasicTeam.Id, gm.Id)
		CheckForbiddenStatus(t, resp)
		// No way into a private channel they are not in: not joining it,
		// reading it or posting to it.
		_, resp, _ = commissionerClient.AddChannelMember(ctx, secret.Id, commissioner.Id)
		CheckForbiddenStatus(t, resp)
		_, resp, _ = commissionerClient.GetPostsForChannel(ctx, secret.Id, 0, 10, "", false, false)
		CheckForbiddenStatus(t, resp)
		_, resp, _ = commissionerClient.CreatePost(ctx, &model.Post{ChannelId: secret.Id, Message: "hello"})
		CheckForbiddenStatus(t, resp)
		// No flipping a channel's privacy, no making a member a channel admin.
		_, resp, _ = commissionerClient.UpdateChannelPrivacy(ctx, private.Id, model.ChannelTypeOpen)
		CheckForbiddenStatus(t, resp)
		resp, _ = commissionerClient.UpdateChannelRoles(ctx, open.Id, gm.Id, "channel_user channel_admin")
		CheckForbiddenStatus(t, resp)
	})

	t.Run("every GM may create a channel (stock team_user)", func(t *testing.T) {
		ch := &model.Channel{DisplayName: "GM room", Name: "gm-room-" + model.NewId()[:6], Type: model.ChannelTypeOpen, TeamId: th.BasicTeam.Id}
		_, resp, _ := gmClient.CreateChannel(ctx, ch)
		CheckCreatedStatus(t, resp)
	})
}
