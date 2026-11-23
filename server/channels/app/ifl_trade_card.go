// IFL: league chat fork (trade cards in direct messages). The site's relay
// posts a trade offer as the proposing GM in their direct message with the
// other GM; only a system admin may create, edit or delete a trade card.
// Hooks: api4/post.go (create, update, patch, delete), api4/scheduled_post.go,
// app/integration_action_setup.go (button responses), app/webhook.go and
// app/command.go (integration posts).
package app

import (
	"net/http"
	"net/url"
	"sync"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/channels/app/ifl"
)

// iflTradeCardLookback is how many of the direct message's latest posts are
// searched for a card the relay already delivered.
const iflTradeCardLookback = 200

// iflTradeCardMu serializes card creation, so two deliveries of the same
// card that arrive together still make one post.
var iflTradeCardMu sync.Mutex

// IFLTradeCardRequest is one trade card for POST /api/v4/ifl/trade_cards.
type IFLTradeCardRequest struct {
	AuthorID    string
	RecipientID string
	TradeID     int64
	Message     string
	Props       model.StringInterface
	Type        string
}

// IFLTradeCardLocked is the refusal for anyone but a system admin who tries
// to create, edit or delete a trade card.
func IFLTradeCardLocked(where string) *model.AppError {
	return model.NewAppError(where, "ifl.trade_card.locked", nil, "", http.StatusForbidden)
}

func iflTradeCardInvalid(name, detail string) *model.AppError {
	return model.NewAppError("IFLPostTradeCard", "api.context.invalid_param.app_error", map[string]any{"Name": name}, detail, http.StatusBadRequest)
}

func (a *App) iflActiveUser(rctx request.CTX, id, name string) (*model.User, *model.AppError) {
	if !model.IsValidId(id) {
		return nil, iflTradeCardInvalid(name, "")
	}
	user, appErr := a.GetUser(rctx, id)
	if appErr != nil {
		if appErr.StatusCode == http.StatusNotFound {
			return nil, iflTradeCardInvalid(name, "no such user")
		}
		return nil, appErr
	}
	if user.DeleteAt != 0 {
		return nil, iflTradeCardInvalid(name, "user is deactivated")
	}
	return user, nil
}

// IFLPostTradeCard posts a trade card as req.AuthorID in the author's direct
// message with req.RecipientID, creating the channel if needed. The relay
// delivers at least once: when the channel already holds the author's card
// for this trade, that post is returned with adopted true and nothing is
// posted. The caller must be a system admin (api4 checks).
func (a *App) IFLPostTradeCard(rctx request.CTX, req IFLTradeCardRequest) (*model.Post, bool, *model.AppError) {
	if req.TradeID <= 0 {
		return nil, false, iflTradeCardInvalid("trade_id", "")
	}
	if req.Type != ifl.TradeCardPostType {
		return nil, false, iflTradeCardInvalid("type", "")
	}
	if id, ok := ifl.TradeCardID(req.Props[ifl.TradeCardIDProp]); !ok || id != req.TradeID {
		return nil, false, iflTradeCardInvalid("props."+ifl.TradeCardIDProp, "must equal trade_id")
	}
	if req.AuthorID == req.RecipientID {
		return nil, false, iflTradeCardInvalid("recipient_id", "must differ from author_id")
	}
	if _, appErr := a.iflActiveUser(rctx, req.AuthorID, "author_id"); appErr != nil {
		return nil, false, appErr
	}
	if _, appErr := a.iflActiveUser(rctx, req.RecipientID, "recipient_id"); appErr != nil {
		return nil, false, appErr
	}

	channel, appErr := a.GetOrCreateDirectChannel(rctx, req.AuthorID, req.RecipientID)
	if appErr != nil {
		return nil, false, appErr
	}

	iflTradeCardMu.Lock()
	defer iflTradeCardMu.Unlock()

	if found, appErr := a.iflFindTradeCard(rctx, channel.Id, req.AuthorID, req.TradeID); appErr != nil || found != nil {
		return found, found != nil, appErr
	}

	post := &model.Post{
		UserId:    req.AuthorID,
		ChannelId: channel.Id,
		Message:   req.Message,
		Type:      req.Type,
	}
	post.SetProps(req.Props)
	saved, _, appErr := a.CreatePost(rctx, post, channel, model.CreatePostFlags{TriggerWebhooks: true})
	if appErr != nil {
		return nil, false, appErr
	}
	return saved, false, nil
}

// iflFindTradeCard is the author's card for tradeID among the channel's
// latest posts, or nil. It reads the master database: a retry can follow
// the first delivery within milliseconds.
func (a *App) iflFindTradeCard(rctx request.CTX, channelID, authorID string, tradeID int64) (*model.Post, *model.AppError) {
	list, err := a.Srv().Store().Post().GetPosts(RequestContextWithMaster(rctx), model.GetPostsOptions{
		ChannelId: channelID, PerPage: iflTradeCardLookback, SkipFetchThreads: true,
	}, false, map[string]bool{})
	if err != nil {
		return nil, model.NewAppError("IFLPostTradeCard", "app.post.get_posts.app_error", nil, "", http.StatusInternalServerError).Wrap(err)
	}
	for _, id := range list.Order {
		post := list.Posts[id]
		if post == nil || post.UserId != authorID || post.DeleteAt != 0 {
			continue
		}
		if got, ok := ifl.TradeCardID(post.GetProp(ifl.TradeCardIDProp)); ok && got == tradeID {
			return post, nil
		}
	}
	return nil, nil
}

// IFLTradeCardActionUpdateRefused reports whether a button's response may
// not apply update to the post: when the post is, or would become, a trade
// card, only iflgm.com's own trade callback may change it. A member's
// button pointing anywhere else must not turn a post into a card or change
// a real one.
func IFLTradeCardActionUpdateRefused(upstreamURL string, originalProps map[string]any, update *model.Post) bool {
	if !ifl.IsTradeCardProps(originalProps) && !ifl.IsTradeCard(update) {
		return false
	}
	u, err := url.Parse(upstreamURL)
	return err != nil || !iflConfig().IsTradeCallback(u)
}
