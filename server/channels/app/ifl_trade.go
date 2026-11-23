// IFL: league chat fork (plan 9). Trading from chat: the /trade command and
// the signing of trade callbacks to iflgm.com.
package app

import (
	"context"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/mlog"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

const iflTradeCenterText = "Use the Trade Center on iflgm.com: https://iflgm.com/my-team?tab=trades"

// iflBuiltInsWithCommandsOff are the built-in slash commands that still run
// while custom slash commands are disabled (as in production): /trade, and
// commands that change only the member's own status or preferences or post
// as the member where they could already post (/me and /shrug in the
// channel, /msg in a direct message the member may open). Every other
// built-in stays refused with upstream's 501: among them /echo (a post
// delayed up to hours, which would land after a suspension), /kick and
// /remove, /invite, /join, /leave, /header, /purpose, /rename, /groupmsg,
// /invite_people, /logout, /settings, /search, /code and /custom_status.
var iflBuiltInsWithCommandsOff = map[string]bool{
	"trade": true, "away": true, "online": true, "offline": true, "dnd": true,
	"me": true, "shrug": true, "msg": true, "mute": true, "expand": true, "collapse": true, "help": true,
}

// iflBuiltInRuns reports whether the built-in command trigger runs while
// custom slash commands are disabled.
func iflBuiltInRuns(trigger string) bool {
	return iflBuiltInsWithCommandsOff[trigger]
}

// iflNoRedirect keeps a signed trade callback from following a redirect:
// Go would copy X-IFL-Chat-Secret to the redirect's host.
func iflNoRedirect(*http.Request, []*http.Request) error {
	return http.ErrUseLastResponse
}

// iflSiteID is the iflgm.com user id of an active, site-linked (GitLab)
// member, or "" for anyone else (bots, detached or deactivated accounts).
func iflSiteID(user *model.User) string {
	if user == nil || user.IsBot || user.DeleteAt != 0 || user.AuthService != model.ServiceGitlab || user.AuthData == nil {
		return ""
	}
	if _, err := strconv.ParseInt(*user.AuthData, 10, 64); err != nil {
		return ""
	}
	return *user.AuthData
}

// iflSignTradeCallback gives a post action or dialog request bound for the
// site's trade callbacks the internal secret and the acting member's site
// id, and reports whether it did. The member is the request session's user,
// never anything the client sent. Every other URL is left alone.
func (a *App) iflSignTradeCallback(rctx request.CTX, inURL *url.URL, req *http.Request) bool {
	cfg := iflConfig()
	if !cfg.IsTradeCallback(inURL) {
		return false
	}
	req.Header.Set(ifl.SecretHeader, cfg.InternalSecret)
	userID := rctx.Session().UserId
	if userID == "" {
		return true
	}
	user, appErr := a.GetUser(rctx, userID)
	if appErr != nil {
		rctx.Logger().Warn("IFL: trade callback without a readable user", mlog.String("user_id", userID), mlog.Err(appErr))
		return true
	}
	if siteID := iflSiteID(user); siteID != "" {
		req.Header.Set(ifl.SiteUserHeader, siteID)
	}
	return true
}

// iflDMPartnerSiteID is the site id of the other member of a direct
// message, or "" (not a DM, a DM with yourself, a bot, or someone who
// doesn't sign in with iflgm.com). The site pre-selects their team.
func (a *App) iflDMPartnerSiteID(rctx request.CTX, channelID, userID string) string {
	channel, appErr := a.GetChannel(rctx, channelID)
	if appErr != nil || channel.Type != model.ChannelTypeDirect {
		return ""
	}
	otherID := channel.GetOtherUserIdForDM(userID)
	if otherID == "" || otherID == userID {
		return ""
	}
	other, appErr := a.GetUser(rctx, otherID)
	if appErr != nil {
		return ""
	}
	return iflSiteID(other)
}

// IFLTradeCommand runs `/trade [team]`: the site decides (chat trading
// gate, partner) and opens the trade dialog with the command's trigger id,
// or answers with text shown only to the member.
func (a *App) IFLTradeCommand(rctx request.CTX, args *model.CommandArgs, message string) *model.CommandResponse {
	reply := func(text string) *model.CommandResponse {
		return &model.CommandResponse{ResponseType: model.CommandResponseTypeEphemeral, Text: text}
	}
	cfg := iflConfig()
	if !cfg.CallbackEnabled() {
		return reply("Trading from chat isn't set up. " + iflTradeCenterText)
	}
	user, appErr := a.GetUser(rctx, args.UserId)
	if appErr != nil {
		return reply("Couldn't start a trade. Try again.")
	}
	siteID := iflSiteID(user)
	if siteID == "" {
		return reply("Only members who sign in with iflgm.com can trade from chat.")
	}
	timeout := time.Duration(*a.Config().ServiceSettings.OutgoingIntegrationRequestsTimeout) * time.Second
	clientTriggerID, _, _, appErr := model.DecodeAndVerifyTriggerId(args.TriggerId, a.AsymmetricSigningKey(), timeout)
	if appErr != nil {
		return reply("Couldn't start a trade. Try again.")
	}
	ctx, cancel := context.WithTimeout(rctx.Context(), 10*time.Second)
	defer cancel()
	res, err := ifl.NewSiteClient(cfg).TradeCommand(ctx, siteID, args.TriggerId, args.ChannelId, message,
		a.iflDMPartnerSiteID(rctx, args.ChannelId, user.Id))
	if err != nil {
		rctx.Logger().Warn("IFL: /trade could not reach iflgm.com", mlog.Err(err))
		return reply("iflgm.com didn't answer. Try again, or " + iflTradeCenterText)
	}
	// The webapp and the phone apps open a dialog only for the trigger id
	// the command response names (handleOpenDialogEvent); built-in commands
	// do not get one from ExecuteCommand, so set it here.
	resp := reply(res.Text)
	resp.TriggerId = clientTriggerID
	return resp
}
