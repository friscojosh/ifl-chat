package ifl

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/mattermost/mattermost/server/public/model"
)

func TestIsTradeCard(t *testing.T) {
	require.False(t, IsTradeCard(nil))
	require.False(t, IsTradeCard(&model.Post{Message: "hi"}))
	require.False(t, IsTradeCard(&model.Post{Type: "custom_other", Props: model.StringInterface{"ifl_trade_cards": 1}}))
	require.True(t, IsTradeCard(&model.Post{Type: TradeCardPostType}))
	require.True(t, IsTradeCard(&model.Post{Props: model.StringInterface{TradeCardIDProp: float64(7)}}))
	require.True(t, IsTradeCard(&model.Post{Props: model.StringInterface{TradeCardProp: map[string]any{}}}))
	require.True(t, IsTradeCard(&model.Post{Props: model.StringInterface{TradeCardProp: nil}}), "a present key counts, whatever its value")
}

func TestTradeCardID(t *testing.T) {
	for v, want := range map[any]int64{float64(42): 42, 42: 42, int64(42): 42, json.Number("42"): 42} {
		got, ok := TradeCardID(v)
		require.True(t, ok, "%T", v)
		require.Equal(t, want, got)
	}
	for _, v := range []any{4.5, "42", nil, json.Number("4.5"), 1e30, true} {
		_, ok := TradeCardID(v)
		require.False(t, ok, "%v", v)
	}
}
