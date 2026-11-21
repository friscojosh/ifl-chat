// IFL: league chat fork (plan 9). `/trade [team]`, a built-in command, so it
// works with custom slash commands disabled (MM_SERVICESETTINGS_ENABLECOMMANDS
// stays false): iflgm.com opens the trade dialog (app/ifl_trade.go).
package slashcommands

import (
	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/shared/i18n"
	"github.com/mattermost/mattermost/server/public/shared/request"
	"github.com/mattermost/mattermost/server/v8/channels/app"
)

type IFLTradeProvider struct {
}

const (
	CmdIFLTrade = "trade"
)

func init() {
	app.RegisterCommandProvider(&IFLTradeProvider{})
}

func (*IFLTradeProvider) GetTrigger() string {
	return CmdIFLTrade
}

func (*IFLTradeProvider) GetCommand(a *app.App, T i18n.TranslateFunc) *model.Command {
	return &model.Command{
		Trigger:          CmdIFLTrade,
		AutoComplete:     true,
		AutoCompleteDesc: "Propose a trade (iflgm.com)",
		AutoCompleteHint: "[team abbreviation]",
		DisplayName:      "trade",
	}
}

func (*IFLTradeProvider) DoCommand(a *app.App, rctx request.CTX, args *model.CommandArgs, message string) *model.CommandResponse {
	return a.IFLTradeCommand(rctx, args, message)
}
