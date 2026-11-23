// IFL: league chat fork (trade cards in direct messages). A trade offer
// is a card the proposing GM "posts" in their direct message with the other
// GM. iflgm.com creates and updates it through the site's relay (a system
// admin); nobody else may create, edit or delete one.
package ifl

import (
	"encoding/json"
	"math"

	"github.com/mattermost/mattermost/server/public/model"
)

const (
	// TradeCardPostType is the post type of a trade card.
	TradeCardPostType = "custom_ifl_trade"
	// TradeCardIDProp holds the card's trade id (an integer).
	TradeCardIDProp = "ifl_trade_card"
	// TradeCardProp holds the card itself (JSON the clients render).
	TradeCardProp = "ifl_trade"
)

// IsTradeCard reports whether post is a trade card: its type is
// TradeCardPostType or its props carry either trade card key, whatever the
// value. Every lock check uses this one test.
func IsTradeCard(post *model.Post) bool {
	if post == nil {
		return false
	}
	return post.Type == TradeCardPostType || IsTradeCardProps(post.GetProps())
}

// IsTradeCardProps reports whether props carry either trade card key.
func IsTradeCardProps(props map[string]any) bool {
	if props == nil {
		return false
	}
	_, hasID := props[TradeCardIDProp]
	_, hasCard := props[TradeCardProp]
	return hasID || hasCard
}

// TradeCardID reads a trade id prop as an integer. Props decoded from JSON
// hold numbers as float64; a fractional, out-of-range or non-numeric value
// is not a trade id.
func TradeCardID(v any) (int64, bool) {
	switch n := v.(type) {
	case float64:
		if n != math.Trunc(n) || math.IsInf(n, 0) || n < math.MinInt64 || n >= math.MaxInt64 {
			return 0, false
		}
		return int64(n), true
	case int:
		return int64(n), true
	case int64:
		return n, true
	case json.Number:
		i, err := n.Int64()
		return i, err == nil
	}
	return 0, false
}
